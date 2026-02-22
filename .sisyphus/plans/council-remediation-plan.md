# Council Remediation Plan

## Phase 1: Signal Script Consolidation

### Task 1.2: Delete signal_check.py and transition crontab

**Status**: COMPLETE

#### Task 1.2.1: Notification channel audit
- [x] Audit check_positions.py notifier channels
- [x] Document results in `artifacts/task-1.2.1-notifier-audit.json`

#### Task 1.2.2: KR duplication monitoring
- [x] Create monitoring template at `logs/phase1-task1.2.2-kr-duplication.md`

#### Task 1.2.3: Post-deployment checklist

##### Post-deployment
- [ ] Docker 이미지 재빌드: `docker build -t turtle-trading .` && `docker-compose up -d turtle-cron`
- [ ] crontab이 check_positions.py를 호출하는지 확인
- [ ] 16:00 KR 시그널 체크 로그 확인 (check_kr.log)
- [ ] 07:00 US 시그널 체크 로그 확인 (check_us.log)
- [ ] Telegram 알림 수신 확인
- [ ] signal_check.py 참조가 남아있지 않은지 grep 확인
- [ ] KR 중복 모니터링 시작 (phase1-task1.2.2-kr-duplication.md)
