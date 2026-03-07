"""
.. deprecated::
    이 모듈은 Playwright 기반 웹 스크래핑 차트 생성기입니다.
    src/local_chart_renderer.py (mplfinance 기반)로 대체되었습니다.
    향후 릴리즈에서 제거 예정. Issue #168 참조.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.async_api import BrowserContext, async_playwright

from src.types import AssetGroup
from src.universe_manager import Asset, UniverseManager

logger = logging.getLogger(__name__)


def get_naver_finance_url(asset: Asset) -> str:
    """
    Asset 정보(국가, 타입)를 바탕으로 네이버 금융 차트 URL을 생성합니다.
    """
    symbol = asset.symbol
    
    # 1. 한국 시장 종목 (예: 삼성전자 005930.KS)
    if asset.country == "KR":
        if symbol.endswith(".KS") or symbol.endswith(".KQ"):
            code = symbol.split(".")[0]
            # KOSPI/KOSDAQ Index
            if code in ["KOSPI", "KOSDAQ"]:
                return f"https://stock.naver.com/domestic/index/{code}/price"
            return f"https://stock.naver.com/domestic/stock/{code}/price"
            
    # 2. 미국 시장 / 기타 글로벌 주식 및 ETF (TradingView 위젯 활용)
    # 네이버 해외주식 UI 파편화 문제로 안정한 TradingView 임베드 활용
    encoded_symbol = quote(symbol)
    macd_study = quote('MACD@tv-basicstudies')
    ma_study = quote('MASimple@tv-basicstudies')
    
    # 지표 통합: MACD, 5/20/60/120 MA 등의 기본 세팅 로드
    studies = f"{macd_study}\x1f{ma_study}" # 0x1F unit separator
    return f"https://s.tradingview.com/widgetembed/?frameElementId=tradingview_1&symbol={encoded_symbol}&interval=D&hidesidetoolbar=1&symboledit=1&saveimage=1&toolbarbg=f1f3f6&studies={quote(studies)}&theme=light&style=1&timezone=Etc%2FUTC"


class UniverseChartFetcher:
    def __init__(self, universe_manager: UniverseManager, max_retries: int = 3, timeout_ms: int = 15000):
        self.universe_manager = universe_manager
        self.max_retries = max_retries
        self.timeout_ms = timeout_ms

    async def _fetch_single_chart(self, context: BrowserContext, asset: Asset, output_path: str) -> bool:
        """단일 종목의 차트를 스크랩하고 결과를 저장합니다."""
        url = get_naver_finance_url(asset)
        logger.info(f"[{asset.symbol}] Fetching chart from: {url}")
        
        page = await context.new_page()
        try:
            # 타임아웃 넉넉히 주되, 페이지 로딩 자체를 못 기다리면 실패
            await page.goto(url, timeout=self.timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            
            # 차트 초기 렌더링 대기
            await page.wait_for_timeout(2000)
            
            # --- 1. 우측 사이드바 숨기기 ---
            try:
                await page.evaluate("""() => {
                    // 완전히 DOM 트리에서 가려버림
                    const rightPanel = document.querySelector('.SidePanel_panel-expand__ML_Xl, .SidePanelWrapper_side-panel-wrapper__bTFQD');
                    if (rightPanel) rightPanel.style.display = 'none';
                    
                    const inner = document.querySelector('.with-right-panel');
                    if (inner) inner.classList.remove('with-right-panel');
                }""")
            except Exception as e:
                logger.warning(f"[{asset.symbol}] 우측 사이드바 숨기기 실패 (무시됨): {e}")

            # 로딩 안정화 대기
            await page.wait_for_timeout(500)

            # --- 네이버 금융(KR) vs TradingView(US) 분기 ---
            if "naver.com" in url:
                # KR 주식: 보조지표 메뉴 열기
                try:
                    await page.evaluate('''() => {
                        const btns = Array.from(document.querySelectorAll('div, button, span'));
                        const openBtn = btns.find(e => e.textContent && e.textContent.includes('보조지표 추가'));
                        if (openBtn) openBtn.click();
                    }''')
                except Exception as e:
                    logger.warning(f"[{asset.symbol}] 보조지표 모달 열기 실패: {e}")
                
                await page.wait_for_timeout(1000)

                # 하단지표 탭 클릭
                try:
                    await page.evaluate('''() => {
                        const lowerTab = Array.from(document.querySelectorAll('button, span, li')).find(e => e.textContent && e.textContent.includes('하단지표'));
                        if (lowerTab) lowerTab.click();
                    }''')
                    await page.wait_for_timeout(1000)
                    
                    # MACD 체크박스 클릭
                    await page.evaluate('''() => {
                        const macd = Array.from(document.querySelectorAll('button, span, label')).find(e => e.textContent === 'MACD');
                        if (macd) macd.click();
                    }''')
                    await page.wait_for_timeout(1000)
                    
                    # 저장 버튼 클릭
                    await page.evaluate('''() => {
                        const saveBtns = Array.from(document.querySelectorAll('button')).filter(e => e.textContent && e.textContent.includes('저장'));
                        if (saveBtns.length > 0) saveBtns[saveBtns.length - 1].click();
                    }''')
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"[{asset.symbol}] 보조지표 설정 부분 실패 (차트는 기본설정으로 캡처): {e}")

                await page.wait_for_timeout(2000)

                # 차트 크롭 (Naver)
                chart_container = page.locator('div[class*="chart-container"], .ciq-chart-area').first
                if await chart_container.is_visible():
                    await chart_container.screenshot(path=output_path, timeout=5000)
                else:
                    logger.warning(f"[{asset.symbol}] 특정 차트 영역 셀렉터를 찾지 못해 전체 화면으로 대체합니다.")
                    await page.screenshot(path=output_path, full_page=True, timeout=5000)

            else:
                # US 주식 (TradingView Widget)
                # 이미 URL 쿼리 파라미터로 지표가 세팅되어 있으므로 바로 캡처 가능
                await page.wait_for_timeout(3000)  # 지표 로딩 넉넉히 대기
                await page.screenshot(path=output_path, full_page=True, timeout=5000)

            return True

        except Exception as e:
            logger.error(f"[{asset.symbol}] 차트 캡처 간 에러 발생: {e}")
            return False
            
        finally:
            await page.close()

    async def fetch_all(self, output_dir: str, limit: Optional[int] = None) -> Dict[str, bool]:
        """
        활성화된 모든 종목에 대해 캡처 배치를 실행합니다.
        결과를 Dict[종목, 성공여부(bool)] 로 반환합니다.
        """
        symbols = self.universe_manager.get_enabled_symbols()
        if limit and limit > 0:
            symbols = symbols[:limit]

        results = {}
        
        async with async_playwright() as p:
            # Mac 환경이나 CI 서버 고려하여 안정성 위주로 headless 런칭
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            # 창 높이를 길게 잡아야 보조지표 메뉴 등이 짤리지 않음
            context = await browser.new_context(viewport={"width": 1440, "height": 1080})
            
            for symbol in symbols:
                asset = self.universe_manager.assets.get(symbol)
                if not asset:
                    continue
                    
                safe_name = re.sub(r'[\\/*?:"<>|]', "", asset.name).replace(" ", "_")
                output_path = f"{output_dir}/{safe_name}_{symbol}.png"
                
                success = False
                for attempt in range(1, self.max_retries + 1):
                    success = await self._fetch_single_chart(context, asset, output_path)
                    if success:
                        break
                    
                    logger.warning(f"[{symbol}] Retry {attempt}/{self.max_retries} failed.")
                    if attempt < self.max_retries:
                        await asyncio.sleep(2)  # Backoff
                        
                results[symbol] = success

            await context.close()
            await browser.close()
            
        return results
