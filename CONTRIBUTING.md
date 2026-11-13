# 기여 안내 / Contributing

- 이슈·풀 리퀘스트 환영합니다. 한국어·영어 모두 좋습니다. *Issues and PRs welcome, in Korean or English.*
- 핵심 기능은 **표준 라이브러리만** 사용합니다. 새 의존성은 선택 기능(없어도 동작)으로만 넣어 주세요.
- 문서 연산은 `hanword_core.py` 에 넣고, 서버(`server.py`)와 CLI(`hanword`)는 얇은 래퍼로 유지합니다.
- 변경 전후로 시험을 돌려 주세요: `cd tests && python -m unittest discover -v -p "test_*.py"`.
  새 형식 처리에는 `tests/corpus/` 에 **직접 만든(합성) 예제 문서**를 추가합니다 — 실제 개인·업무 문서는 넣지 마세요.
- 보안 문제는 공개 이슈 대신 [SECURITY.md](SECURITY.md) 절차로 알려 주세요.
- 기여한 코드는 MIT 라이선스로 배포됩니다.
