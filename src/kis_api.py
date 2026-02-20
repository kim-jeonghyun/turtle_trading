"""
한국투자증권 KIS API 클라이언트
- 국내주식 조회/주문
- 해외주식 조회/주문
- 재시도 (지수 백오프), 레이트 리밋, 세션 재사용
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional

import aiohttp

from src.utils import retry_async

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class KISAPIError(Exception):
    """Base KIS API error"""

    pass


class RetryableError(KISAPIError):
    """Network timeout, 5xx -- should retry"""

    pass


class FatalError(KISAPIError):
    """400, 403 -- should NOT retry"""

    pass


class TokenExpiredError(KISAPIError):
    """401 -- token expired, should refresh and retry once"""

    pass


class RateLimitError(KISAPIError):
    """429 -- wait and retry"""

    pass


def _sanitize_error(data) -> str:
    """예외 메시지용 안전한 요약 생성 (민감 데이터 제외)"""
    if not isinstance(data, dict):
        return "rt_cd=N/A, msg=N/A"
    rt_cd = data.get("rt_cd", "N/A")
    msg1 = data.get("msg1", "N/A")
    return f"rt_cd={rt_cd}, msg={msg1}"


def _classify_response(status: int, data: dict) -> None:
    """HTTP 응답 코드 기반 예외 분류 (성공 시 None 반환)"""
    if 200 <= status < 300:
        return  # 성공

    safe_msg = _sanitize_error(data)
    # NOTE: debug 레벨에서 전체 응답 출력 — 프로덕션 로그 수집기가
    # debug를 포함하지 않도록 운영 정책에서 관리 필요
    logger.debug("API error response (status=%d): %s", status, data)

    if status == 429:
        raise RateLimitError(f"Rate limit exceeded: {safe_msg}")
    if status == 401:
        raise TokenExpiredError(f"Token expired (401): {safe_msg}")
    if status in (400, 403):
        raise FatalError(f"Client error {status}: {safe_msg}")
    if status >= 500:
        raise RetryableError(f"Server error {status}: {safe_msg}")
    raise KISAPIError(f"Unexpected status {status}: {safe_msg}")


class KISMarket(Enum):
    KOREA = "KOR"
    USA = "USA"
    JAPAN = "JPN"
    CHINA_SH = "SHS"
    CHINA_SZ = "SZS"
    HONGKONG = "HKS"
    VIETNAM = "VNM"


class OrderType(Enum):
    MARKET = "01"
    LIMIT = "00"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class KISConfig:
    app_key: str
    app_secret: str
    account_no: str
    account_suffix: str = "01"
    is_real: bool = False

    @property
    def base_url(self) -> str:
        if self.is_real:
            return "https://openapi.koreainvestment.com:9443"
        return "https://openapivts.koreainvestment.com:29443"


@dataclass
class KISToken:
    access_token: str
    expires_at: datetime


class KISAPIClient:
    def __init__(self, config: KISConfig):
        self.config = config
        self.token: Optional[KISToken] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(18)  # KIS 20 req/sec, 2 buffer
        self._token_lock = asyncio.Lock()  # 토큰 갱신 직렬화

    # --- Context manager for session reuse ---

    async def __aenter__(self):
        self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self

    async def __aexit__(self, *args):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def _get_session(self) -> aiohttp.ClientSession:
        """관리 세션 반환, 없으면 임시 세션은 호출측에서 생성"""
        if self._session and not self._session.closed:
            return self._session
        return None

    @retry_async(
        max_retries=3,
        base_delay=1.0,
        exceptions=(RetryableError, RateLimitError, ConnectionError, TimeoutError, aiohttp.ClientError),
    )
    async def _get_token(self) -> str:
        async with self._token_lock:
            if self.token and datetime.now() < self.token.expires_at:
                return self.token.access_token

            url = f"{self.config.base_url}/oauth2/tokenP"
            payload = {
                "grant_type": "client_credentials",
                "appkey": self.config.app_key,
                "appsecret": self.config.app_secret,
            }

            managed = self._get_session()
            session_to_close = None
            if managed is None:
                managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
                session_to_close = managed

            try:
                async with self._semaphore:
                    async with managed.post(url, json=payload) as resp:
                        data = await resp.json()
                        _classify_response(resp.status, data)
                        if "access_token" in data:
                            self.token = KISToken(
                                access_token=data["access_token"], expires_at=datetime.now() + timedelta(hours=23)
                            )
                            logger.info("KIS 토큰 발급 성공")
                            return self.token.access_token
                        else:
                            raise FatalError(
                                f"토큰 발급 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                            )
            finally:
                if session_to_close:
                    await session_to_close.close()

    async def _invalidate_and_refresh_token(self) -> str:
        """토큰 무효화 후 재발급 (401 응답 시 사용)"""
        logger.warning("토큰 만료 감지 — 재발급 시도")
        self.token = None
        return await self._get_token()

    def _classify_and_handle(self, status: int, data: dict) -> None:
        """응답 분류 + 401 시 캐시된 토큰 무효화 (retry_async가 재시도 시 새 토큰 사용)"""
        try:
            _classify_response(status, data)
        except TokenExpiredError:
            self.token = None  # 캐시 무효화 → 재시도 시 _get_token()이 새 토큰 발급
            raise

    def _get_headers(self, token: str, tr_id: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    @retry_async(
        max_retries=3,
        base_delay=1.0,
        exceptions=(
            RetryableError,
            RateLimitError,
            TokenExpiredError,
            ConnectionError,
            TimeoutError,
            aiohttp.ClientError,
        ),
    )
    async def get_korea_price(self, symbol: str) -> Dict[str, Any]:
        """국내 주식 현재가 조회"""
        token = await self._get_token()
        tr_id = "FHKST01010100" if self.config.is_real else "FHKST01010100"

        url = f"{self.config.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._get_headers(token, tr_id)
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.get(url, headers=headers, params=params) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise RetryableError(f"JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output = data.get("output", {})
                        return {
                            "symbol": symbol,
                            "price": float(output.get("stck_prpr", 0)),
                            "change": float(output.get("prdy_vrss", 0)),
                            "change_pct": float(output.get("prdy_ctrt", 0)),
                            "volume": int(output.get("acml_vol", 0)),
                            "high": float(output.get("stck_hgpr", 0)),
                            "low": float(output.get("stck_lwpr", 0)),
                            "open": float(output.get("stck_oprc", 0)),
                        }
                    else:
                        logger.error(
                            f"가격 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                        )
                        return {}
        finally:
            if session_to_close:
                await session_to_close.close()

    @retry_async(
        max_retries=3,
        base_delay=1.0,
        exceptions=(
            RetryableError,
            RateLimitError,
            TokenExpiredError,
            ConnectionError,
            TimeoutError,
            aiohttp.ClientError,
        ),
    )
    async def get_overseas_price(self, symbol: str, market: KISMarket = KISMarket.USA) -> Dict[str, Any]:
        """해외 주식 현재가 조회"""
        token = await self._get_token()
        tr_id = "HHDFS00000300" if self.config.is_real else "HHDFS00000300"

        url = f"{self.config.base_url}/uapi/overseas-price/v1/quotations/price"
        headers = self._get_headers(token, tr_id)

        excd_map = {KISMarket.USA: "NAS", KISMarket.JAPAN: "TSE", KISMarket.HONGKONG: "HKS"}

        params = {"AUTH": "", "EXCD": excd_map.get(market, "NAS"), "SYMB": symbol}

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.get(url, headers=headers, params=params) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise RetryableError(f"JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output = data.get("output", {})
                        return {
                            "symbol": symbol,
                            "price": float(output.get("last", 0)),
                            "change": float(output.get("diff", 0)),
                            "change_pct": float(output.get("rate", 0)),
                            "volume": int(output.get("tvol", 0)),
                            "high": float(output.get("high", 0)),
                            "low": float(output.get("low", 0)),
                            "open": float(output.get("open", 0)),
                        }
                    else:
                        logger.error(
                            f"해외 가격 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                        )
                        return {}
        finally:
            if session_to_close:
                await session_to_close.close()

    @retry_async(
        max_retries=3,
        base_delay=1.0,
        exceptions=(
            RetryableError,
            RateLimitError,
            TokenExpiredError,
            ConnectionError,
            TimeoutError,
            aiohttp.ClientError,
        ),
    )
    async def get_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회"""
        token = await self._get_token()
        tr_id = "TTTC8434R" if self.config.is_real else "VTTC8434R"

        url = f"{self.config.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self._get_headers(token, tr_id)
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.get(url, headers=headers, params=params) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise RetryableError(f"JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output1 = data.get("output1", [])
                        output2 = data.get("output2", [{}])[0]

                        positions = []
                        for item in output1:
                            if int(item.get("hldg_qty", 0)) > 0:
                                positions.append(
                                    {
                                        "symbol": item.get("pdno"),
                                        "name": item.get("prdt_name"),
                                        "quantity": int(item.get("hldg_qty", 0)),
                                        "avg_price": float(item.get("pchs_avg_pric", 0)),
                                        "current_price": float(item.get("prpr", 0)),
                                        "pnl": float(item.get("evlu_pfls_amt", 0)),
                                        "pnl_pct": float(item.get("evlu_pfls_rt", 0)),
                                    }
                                )

                        return {
                            "total_equity": float(output2.get("tot_evlu_amt", 0)),
                            "cash": float(output2.get("dnca_tot_amt", 0)),
                            "positions": positions,
                        }
                    else:
                        logger.error(
                            f"잔고 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                        )
                        return {}
        finally:
            if session_to_close:
                await session_to_close.close()

    # 주문 메서드는 멱등성 미보장이므로 @retry_async 적용하지 않음
    # 5xx 후 재시도 시 중복 주문 위험
    async def place_order(
        self, symbol: str, side: OrderSide, quantity: int, price: float = 0, order_type: OrderType = OrderType.MARKET
    ) -> Dict[str, Any]:
        """국내 주식 주문"""
        token = await self._get_token()

        if side == OrderSide.BUY:
            tr_id = "TTTC0802U" if self.config.is_real else "VTTC0802U"
        else:
            tr_id = "TTTC0801U" if self.config.is_real else "VTTC0801U"

        url = f"{self.config.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self._get_headers(token, tr_id)

        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "PDNO": symbol,
            "ORD_DVSN": order_type.value,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(int(price)) if order_type == OrderType.LIMIT else "0",
        }

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.post(url, headers=headers, json=payload) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise KISAPIError(f"주문 응답 JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output = data.get("output", {})
                        logger.info(f"주문 성공: {symbol} {side.value} {quantity}")
                        return {"success": True, "order_no": output.get("ODNO"), "order_time": output.get("ORD_TMD")}
                    else:
                        logger.error(f"주문 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                        return {"success": False, "message": data.get("msg1", "Unknown error")}
        finally:
            if session_to_close:
                await session_to_close.close()

    # 주문 메서드는 멱등성 미보장이므로 @retry_async 적용하지 않음
    async def place_overseas_order(
        self, symbol: str, side: OrderSide, quantity: int, price: float, market: KISMarket = KISMarket.USA
    ) -> Dict[str, Any]:
        """해외 주식 주문"""
        token = await self._get_token()

        if side == OrderSide.BUY:
            tr_id = "JTTT1002U" if self.config.is_real else "VTTT1002U"
        else:
            tr_id = "JTTT1006U" if self.config.is_real else "VTTT1006U"

        url = f"{self.config.base_url}/uapi/overseas-stock/v1/trading/order"
        headers = self._get_headers(token, tr_id)

        excd_map = {KISMarket.USA: "NASD", KISMarket.JAPAN: "TKSE", KISMarket.HONGKONG: "SEHK"}

        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "OVRS_EXCG_CD": excd_map.get(market, "NASD"),
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00",
        }

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.post(url, headers=headers, json=payload) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise KISAPIError(f"해외 주문 응답 JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output = data.get("output", {})
                        logger.info(f"해외 주문 성공: {symbol} {side.value} {quantity}")
                        return {"success": True, "order_no": output.get("ODNO"), "order_time": output.get("ORD_TMD")}
                    else:
                        logger.error(
                            f"해외 주문 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                        )
                        return {"success": False, "message": data.get("msg1", "Unknown error")}
        finally:
            if session_to_close:
                await session_to_close.close()

    @retry_async(
        max_retries=3,
        base_delay=1.0,
        exceptions=(
            RetryableError,
            RateLimitError,
            TokenExpiredError,
            ConnectionError,
            TimeoutError,
            aiohttp.ClientError,
        ),
    )
    async def get_order_status(self, order_no: str) -> dict:
        """KIS 주문체결조회 API

        /uapi/domestic-stock/v1/trading/inquire-daily-ccld 엔드포인트 사용

        Args:
            order_no: KIS 주문 번호

        Returns:
            주문 상태 딕셔너리
        """
        token = await self._get_token()
        tr_id = "TTTC8001R" if self.config.is_real else "VTTC8001R"

        url = f"{self.config.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        headers = self._get_headers(token, tr_id)
        params = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"),
            "INQR_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",  # 전체 (매수+매도)
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": order_no,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        managed = self._get_session()
        session_to_close = None
        if managed is None:
            managed = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            session_to_close = managed

        try:
            async with self._semaphore:
                async with managed.get(url, headers=headers, params=params) as resp:
                    try:
                        data = await resp.json()
                    except (aiohttp.ContentTypeError, ValueError) as e:
                        raise RetryableError(f"JSON 파싱 실패 (status={resp.status}): {e}")
                    self._classify_and_handle(resp.status, data)
                    if data.get("rt_cd") == "0":
                        output_list = data.get("output1", [])
                        # 해당 주문번호에 대한 체결 내역 필터
                        matched = [o for o in output_list if o.get("odno") == order_no]
                        if matched:
                            item = matched[0]
                            return {
                                "order_no": order_no,
                                "status": "filled" if float(item.get("tot_ccld_qty", 0)) > 0 else "pending",
                                "symbol": item.get("pdno", ""),
                                "side": "buy" if item.get("sll_buy_dvsn_cd") == "02" else "sell",
                                "order_qty": int(item.get("ord_qty", 0)),
                                "filled_qty": int(item.get("tot_ccld_qty", 0)),
                                "filled_price": float(item.get("avg_prvs", 0)),
                                "order_time": item.get("ord_tmd", ""),
                            }
                        return {"order_no": order_no, "status": "not_found", "message": "주문 내역을 찾을 수 없음"}
                    else:
                        logger.error(
                            f"주문 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}"
                        )
                        return {"order_no": order_no, "status": "error", "message": data.get("msg1", "Unknown error")}
        finally:
            if session_to_close:
                await session_to_close.close()
