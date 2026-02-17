"""
포지션 추적 및 관리 모듈
- 진입/청산 이력 관리
- 오픈 포지션 추적
- 청산 시그널 감지
- 피라미딩 관리
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from .utils import atomic_write_json, backup_file, validate_position_schema, safe_load_json

logger = logging.getLogger(__name__)


class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"  # 부분 청산


class SignalType(Enum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    PYRAMID = "pyramid"
    STOP_LOSS = "stop_loss"


@dataclass
class Position:
    """포지션 데이터 클래스"""
    position_id: str
    symbol: str
    system: int  # 1 or 2
    direction: str  # LONG or SHORT

    # 진입 정보
    entry_date: str
    entry_price: float
    entry_n: float  # 진입 시점의 N (ATR)

    # 수량 정보
    units: int  # 현재 유닛 수
    max_units: int  # 최대 유닛 수 (보통 4)
    shares_per_unit: int  # 유닛당 주식 수
    total_shares: int  # 총 주식 수

    # 리스크 관리
    stop_loss: float  # 스톱로스 가격 (진입가 - 2N)
    pyramid_level: int  # 피라미딩 레벨 (0=초기 진입)

    # 청산 조건
    exit_period: int  # 청산 기간 (System 1: 10일, System 2: 20일)

    # 상태
    status: str  # open, closed, partial
    last_update: str

    # 청산 정보 (청산 시에만)
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None  # N의 배수로 수익 표현

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        return cls(**data)

    def calculate_pnl(self, exit_price: float) -> float:
        """손익 계산"""
        if self.direction == "LONG":
            return (exit_price - self.entry_price) * self.total_shares
        else:  # SHORT
            return (self.entry_price - exit_price) * self.total_shares

    def calculate_r_multiple(self, exit_price: float) -> float:
        """R-배수 계산 (리스크 대비 수익)"""
        pnl_per_share = exit_price - self.entry_price if self.direction == "LONG" else self.entry_price - exit_price
        risk_per_share = 2 * self.entry_n  # 2N 리스크
        return pnl_per_share / risk_per_share if risk_per_share > 0 else 0


@dataclass
class PositionEntry:
    """개별 진입 기록 (피라미딩 추적용)"""
    entry_id: str
    position_id: str
    entry_date: str
    entry_price: float
    shares: int
    pyramid_level: int
    n_value: float


class PositionTracker:
    """포지션 추적 및 관리"""

    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.positions_dir = self.base_dir / "positions"
        self.entries_dir = self.base_dir / "entries"

        for d in [self.positions_dir, self.entries_dir]:
            d.mkdir(parents=True, exist_ok=True)

        self.positions_file = self.positions_dir / "positions.json"
        self.entries_file = self.entries_dir / "entries.json"

        self._init_files()

    def _init_files(self):
        """파일 초기화"""
        if not self.positions_file.exists():
            self._save_positions([])
        if not self.entries_file.exists():
            self._save_entries([])

    def _load_positions(self) -> List[Position]:
        """모든 포지션 로드 (스키마 검증 포함)"""
        data = safe_load_json(self.positions_file, default=[])
        valid_positions = []
        for p in data:
            if validate_position_schema(p):
                valid_positions.append(Position.from_dict(p))
            else:
                logger.warning(f"잘못된 포지션 데이터 스킵: {p.get('position_id', 'unknown')}")
        return valid_positions

    def _save_positions(self, positions: List[Position]):
        """포지션 저장 (atomic write + 백업)"""
        backup_file(self.positions_file)
        data = [p.to_dict() for p in positions]
        atomic_write_json(self.positions_file, data)

    def _load_entries(self) -> List[PositionEntry]:
        """모든 진입 기록 로드"""
        data = safe_load_json(self.entries_file, default=[])
        return [PositionEntry(**e) for e in data]

    def _save_entries(self, entries: List[PositionEntry]):
        """진입 기록 저장 (atomic write + 백업)"""
        backup_file(self.entries_file)
        data = [asdict(e) for e in entries]
        atomic_write_json(self.entries_file, data)

    def open_position(
        self,
        symbol: str,
        system: int,
        direction: str,
        entry_price: float,
        n_value: float,
        shares: int,
        account_equity: float = 100000
    ) -> Position:
        """새 포지션 생성"""
        position_id = f"{symbol}_{system}_{direction}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 청산 기간 설정
        exit_period = 10 if system == 1 else 20

        # 스톱로스 계산
        if direction == "LONG":
            stop_loss = entry_price - (2 * n_value)
        else:  # SHORT
            stop_loss = entry_price + (2 * n_value)

        position = Position(
            position_id=position_id,
            symbol=symbol,
            system=system,
            direction=direction,
            entry_date=datetime.now().strftime('%Y-%m-%d'),
            entry_price=entry_price,
            entry_n=n_value,
            units=1,
            max_units=4,
            shares_per_unit=shares,
            total_shares=shares,
            stop_loss=stop_loss,
            pyramid_level=0,
            exit_period=exit_period,
            status=PositionStatus.OPEN.value,
            last_update=datetime.now().isoformat()
        )

        # 포지션 저장
        positions = self._load_positions()
        positions.append(position)
        self._save_positions(positions)

        # 진입 기록 저장
        entry = PositionEntry(
            entry_id=f"{position_id}_0",
            position_id=position_id,
            entry_date=position.entry_date,
            entry_price=entry_price,
            shares=shares,
            pyramid_level=0,
            n_value=n_value
        )
        entries = self._load_entries()
        entries.append(entry)
        self._save_entries(entries)

        logger.info(f"포지션 오픈: {symbol} {direction} @ {entry_price}")
        return position

    def add_pyramid(
        self,
        position_id: str,
        entry_price: float,
        n_value: float,
        shares: int
    ) -> Optional[Position]:
        """피라미딩 추가"""
        positions = self._load_positions()

        for i, pos in enumerate(positions):
            if pos.position_id == position_id and pos.status == PositionStatus.OPEN.value:
                if pos.units >= pos.max_units:
                    logger.warning(f"최대 유닛 도달: {position_id}")
                    return None

                # 유닛 추가
                pos.units += 1
                pos.total_shares += shares
                pos.pyramid_level += 1
                pos.last_update = datetime.now().isoformat()

                # 진입 기록 추가
                entry = PositionEntry(
                    entry_id=f"{position_id}_{pos.pyramid_level}",
                    position_id=position_id,
                    entry_date=datetime.now().strftime('%Y-%m-%d'),
                    entry_price=entry_price,
                    shares=shares,
                    pyramid_level=pos.pyramid_level,
                    n_value=n_value
                )
                entries = self._load_entries()
                entries.append(entry)
                self._save_entries(entries)

                positions[i] = pos
                self._save_positions(positions)

                logger.info(f"피라미딩 추가: {position_id} Level {pos.pyramid_level}")
                return pos

        return None

    def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_reason: str = "Exit Signal"
    ) -> Optional[Position]:
        """포지션 청산"""
        positions = self._load_positions()

        for i, pos in enumerate(positions):
            if pos.position_id == position_id and pos.status == PositionStatus.OPEN.value:
                pos.exit_date = datetime.now().strftime('%Y-%m-%d')
                pos.exit_price = exit_price
                pos.exit_reason = exit_reason
                pos.pnl = pos.calculate_pnl(exit_price)
                pos.pnl_pct = (pos.pnl / (pos.entry_price * pos.total_shares)) * 100
                pos.r_multiple = pos.calculate_r_multiple(exit_price)
                pos.status = PositionStatus.CLOSED.value
                pos.last_update = datetime.now().isoformat()

                positions[i] = pos
                self._save_positions(positions)

                logger.info(f"포지션 청산: {position_id} PnL: {pos.pnl:,.0f} ({pos.r_multiple:.2f}R)")
                return pos

        return None

    def get_all_positions(self) -> List[Position]:
        """모든 포지션 반환 (오픈 + 청산)"""
        return self._load_positions()

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """오픈 포지션 조회"""
        positions = self._load_positions()
        open_pos = [p for p in positions if p.status == PositionStatus.OPEN.value]

        if symbol:
            open_pos = [p for p in open_pos if p.symbol == symbol]

        return open_pos

    def get_position(self, position_id: str) -> Optional[Position]:
        """특정 포지션 조회"""
        positions = self._load_positions()
        for pos in positions:
            if pos.position_id == position_id:
                return pos
        return None

    def get_position_history(self, symbol: str) -> List[Position]:
        """종목별 포지션 이력"""
        positions = self._load_positions()
        return [p for p in positions if p.symbol == symbol]

    def get_entries(self, position_id: str) -> List[PositionEntry]:
        """포지션의 모든 진입 기록"""
        entries = self._load_entries()
        return [e for e in entries if e.position_id == position_id]

    def check_stop_loss(self, current_price: float) -> List[Position]:
        """스톱로스 체크"""
        positions = self.get_open_positions()
        to_close = []

        for pos in positions:
            if pos.direction == "LONG" and current_price <= pos.stop_loss:
                to_close.append(pos)
            elif pos.direction == "SHORT" and current_price >= pos.stop_loss:
                to_close.append(pos)

        return to_close

    def should_pyramid(self, position: Position, current_price: float) -> bool:
        """피라미딩 기회 확인"""
        if position.units >= position.max_units:
            return False

        # 마지막 진입가 대비 0.5N 상승 확인
        entries = self.get_entries(position.position_id)
        if not entries:
            return False

        last_entry = max(entries, key=lambda e: e.pyramid_level)
        threshold = 0.5 * position.entry_n

        if position.direction == "LONG":
            return current_price >= last_entry.entry_price + threshold
        else:  # SHORT
            return current_price <= last_entry.entry_price - threshold

    def get_summary(self) -> Dict[str, Any]:
        """포지션 요약"""
        positions = self._load_positions()
        open_pos = [p for p in positions if p.status == PositionStatus.OPEN.value]
        closed_pos = [p for p in positions if p.status == PositionStatus.CLOSED.value]

        total_pnl = sum(p.pnl for p in closed_pos if p.pnl is not None)
        winning_trades = [p for p in closed_pos if p.pnl and p.pnl > 0]

        return {
            "total_positions": len(positions),
            "open_positions": len(open_pos),
            "closed_positions": len(closed_pos),
            "total_pnl": total_pnl,
            "winning_trades": len(winning_trades),
            "win_rate": len(winning_trades) / len(closed_pos) if closed_pos else 0,
            "avg_r_multiple": sum(p.r_multiple for p in closed_pos if p.r_multiple) / len(closed_pos) if closed_pos else 0
        }
