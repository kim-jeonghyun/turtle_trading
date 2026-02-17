"""
한국투자증권 KIS API 클라이언트
- 국내주식 조회/주문
- 해외주식 조회/주문
"""

import aiohttp
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


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

    async def _get_token(self) -> str:
        if self.token and datetime.now() < self.token.expires_at:
            return self.token.access_token

        url = f"{self.config.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if "access_token" in data:
                    self.token = KISToken(
                        access_token=data["access_token"],
                        expires_at=datetime.now() + timedelta(hours=23)
                    )
                    logger.info("KIS 토큰 발급 성공")
                    return self.token.access_token
                else:
                    raise Exception(f"토큰 발급 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")

    def _get_headers(self, token: str, tr_id: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }

    async def get_korea_price(self, symbol: str) -> Dict[str, Any]:
        """국내 주식 현재가 조회"""
        token = await self._get_token()
        tr_id = "FHKST01010100" if self.config.is_real else "FHKST01010100"

        url = f"{self.config.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._get_headers(token, tr_id)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()
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
                        "open": float(output.get("stck_oprc", 0))
                    }
                else:
                    logger.error(f"가격 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                    return {}

    async def get_overseas_price(self, symbol: str, market: KISMarket = KISMarket.USA) -> Dict[str, Any]:
        """해외 주식 현재가 조회"""
        token = await self._get_token()
        tr_id = "HHDFS00000300" if self.config.is_real else "HHDFS00000300"

        url = f"{self.config.base_url}/uapi/overseas-price/v1/quotations/price"
        headers = self._get_headers(token, tr_id)

        excd_map = {
            KISMarket.USA: "NAS",
            KISMarket.JAPAN: "TSE",
            KISMarket.HONGKONG: "HKS"
        }

        params = {
            "AUTH": "",
            "EXCD": excd_map.get(market, "NAS"),
            "SYMB": symbol
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()
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
                        "open": float(output.get("open", 0))
                    }
                else:
                    logger.error(f"해외 가격 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                    return {}

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
            "CTX_AREA_NK100": ""
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()
                if data.get("rt_cd") == "0":
                    output1 = data.get("output1", [])
                    output2 = data.get("output2", [{}])[0]

                    positions = []
                    for item in output1:
                        if int(item.get("hldg_qty", 0)) > 0:
                            positions.append({
                                "symbol": item.get("pdno"),
                                "name": item.get("prdt_name"),
                                "quantity": int(item.get("hldg_qty", 0)),
                                "avg_price": float(item.get("pchs_avg_pric", 0)),
                                "current_price": float(item.get("prpr", 0)),
                                "pnl": float(item.get("evlu_pfls_amt", 0)),
                                "pnl_pct": float(item.get("evlu_pfls_rt", 0))
                            })

                    return {
                        "total_equity": float(output2.get("tot_evlu_amt", 0)),
                        "cash": float(output2.get("dnca_tot_amt", 0)),
                        "positions": positions
                    }
                else:
                    logger.error(f"잔고 조회 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                    return {}

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float = 0,
        order_type: OrderType = OrderType.MARKET
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
            "ORD_UNPR": str(int(price)) if order_type == OrderType.LIMIT else "0"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    logger.info(f"주문 성공: {symbol} {side.value} {quantity}")
                    return {
                        "success": True,
                        "order_no": output.get("ODNO"),
                        "order_time": output.get("ORD_TMD")
                    }
                else:
                    logger.error(f"주문 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                    return {
                        "success": False,
                        "message": data.get("msg1", "Unknown error")
                    }

    async def place_overseas_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float,
        market: KISMarket = KISMarket.USA
    ) -> Dict[str, Any]:
        """해외 주식 주문"""
        token = await self._get_token()

        if side == OrderSide.BUY:
            tr_id = "JTTT1002U" if self.config.is_real else "VTTT1002U"
        else:
            tr_id = "JTTT1006U" if self.config.is_real else "VTTT1006U"

        url = f"{self.config.base_url}/uapi/overseas-stock/v1/trading/order"
        headers = self._get_headers(token, tr_id)

        excd_map = {
            KISMarket.USA: "NASD",
            KISMarket.JAPAN: "TKSE",
            KISMarket.HONGKONG: "SEHK"
        }

        payload = {
            "CANO": self.config.account_no,
            "ACNT_PRDT_CD": self.config.account_suffix,
            "OVRS_EXCG_CD": excd_map.get(market, "NASD"),
            "PDNO": symbol,
            "ORD_QTY": str(quantity),
            "OVRS_ORD_UNPR": str(price),
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": "00"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                data = await resp.json()
                if data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    logger.info(f"해외 주문 성공: {symbol} {side.value} {quantity}")
                    return {
                        "success": True,
                        "order_no": output.get("ODNO"),
                        "order_time": output.get("ORD_TMD")
                    }
                else:
                    logger.error(f"해외 주문 실패: rt_cd={data.get('rt_cd', 'UNKNOWN')}, msg={data.get('msg1', '')}")
                    return {
                        "success": False,
                        "message": data.get("msg1", "Unknown error")
                    }
