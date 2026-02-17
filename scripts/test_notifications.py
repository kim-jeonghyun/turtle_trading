"""
알림 시스템 테스트 스크립트
- Telegram, Discord, Email 연결 테스트
"""

import asyncio
import os
from dotenv import load_dotenv
from pathlib import Path
import sys

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.notifier import (
    TelegramChannel,
    DiscordChannel,
    EmailChannel,
    NotificationMessage,
    NotificationLevel
)

load_dotenv()


async def test_telegram():
    """Telegram 알림 테스트"""
    print("\n" + "="*50)
    print("📱 Telegram 알림 테스트")
    print("="*50)

    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        print('❌ TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다.')
        return False

    print(f'✅ Bot Token: {"[SET]" if bot_token else "[NOT SET]"}')
    print(f'✅ Chat ID: {"[SET]" if chat_id else "[NOT SET]"}')

    channel = TelegramChannel(bot_token, chat_id)
    message = NotificationMessage(
        title='🐢 Turtle Trading 시스템 테스트',
        body='Telegram 알림이 정상적으로 작동합니다!',
        level=NotificationLevel.INFO,
        data={
            '시스템': 'Turtle Trading v2.0',
            '상태': '정상'
        }
    )

    print('📤 메시지 전송 중...')
    success = await channel.send(message)

    if success:
        print('✅ Telegram 메시지 전송 성공!')
    else:
        print('❌ Telegram 메시지 전송 실패')

    return success


async def test_discord():
    """Discord 알림 테스트"""
    print("\n" + "="*50)
    print("💬 Discord 알림 테스트")
    print("="*50)

    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')

    if not webhook_url or webhook_url == 'https://discord.com/api/webhooks/xxx/yyy':
        print('⏭️  Discord 웹훅이 설정되지 않았습니다. 건너뜁니다.')
        return None

    print(f'✅ Webhook URL: {"[SET]" if webhook_url else "[NOT SET]"}')

    channel = DiscordChannel(webhook_url)
    message = NotificationMessage(
        title='🐢 Turtle Trading 시스템 테스트',
        body='Discord 알림이 정상적으로 작동합니다!',
        level=NotificationLevel.INFO,
        data={
            '시스템': 'Turtle Trading v2.0',
            '상태': '정상'
        }
    )

    print('📤 메시지 전송 중...')
    success = await channel.send(message)

    if success:
        print('✅ Discord 메시지 전송 성공!')
    else:
        print('❌ Discord 메시지 전송 실패')

    return success


async def test_email():
    """Email 알림 테스트"""
    print("\n" + "="*50)
    print("📧 Email 알림 테스트")
    print("="*50)

    smtp_host = os.getenv('SMTP_HOST')
    email_user = os.getenv('EMAIL_USER')
    email_password = os.getenv('EMAIL_PASSWORD')
    email_to = os.getenv('EMAIL_TO')

    if not all([smtp_host, email_user, email_password, email_to]):
        print('⏭️  Email 설정이 완료되지 않았습니다. 건너뜁니다.')
        return None

    print(f'✅ SMTP Host: {smtp_host}')
    print(f'✅ From: {email_user}')
    print(f'✅ To: {email_to}')

    smtp_port = int(os.getenv('SMTP_PORT', '587'))

    channel = EmailChannel(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=email_user,
        password=email_password,
        from_addr=email_user,
        to_addrs=email_to.split(',')
    )

    message = NotificationMessage(
        title='🐢 Turtle Trading 시스템 테스트',
        body='Email 알림이 정상적으로 작동합니다!',
        level=NotificationLevel.INFO,
        data={
            '시스템': 'Turtle Trading v2.0',
            '상태': '정상'
        }
    )

    print('📤 메시지 전송 중...')
    success = await channel.send(message)

    if success:
        print('✅ Email 전송 성공!')
    else:
        print('❌ Email 전송 실패')

    return success


async def main():
    """모든 알림 채널 테스트"""
    print("\n🧪 알림 시스템 종합 테스트 시작\n")

    results = {
        'Telegram': await test_telegram(),
        'Discord': await test_discord(),
        'Email': await test_email()
    }

    print("\n" + "="*50)
    print("📊 테스트 결과 요약")
    print("="*50)

    for channel, result in results.items():
        if result is True:
            print(f'✅ {channel}: 성공')
        elif result is False:
            print(f'❌ {channel}: 실패')
        else:
            print(f'⏭️  {channel}: 건너뜀')

    success_count = sum(1 for r in results.values() if r is True)
    total_tested = sum(1 for r in results.values() if r is not None)

    print(f'\n성공: {success_count}/{total_tested}')
    print("="*50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
