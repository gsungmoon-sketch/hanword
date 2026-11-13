"""시간 시험 도우미 — 2차 시간 검출은 절대 초가 아니라 크기 n → 4n 배율로(느린 CI 러너에서도 안정).

  HANWORD_TIME_SCALE (기본 1): 절대 상한 배수. 느린 러너는 CI 가 키운다(release/ci 워크플로).
  assert_linear: t(4n)/t(n) < RATIO(6; 선형=4, 2차=16). t(4n) 이 FLOOR 초 미만이면 잡음이라 통과.
  t(n) 이 cap×SCALE 를 넘으면 4n 을 돌리지 않고 바로 실패(2차면 4n 은 16배 걸리므로).
"""
import os, time

SCALE = max(1.0, float(os.environ.get("HANWORD_TIME_SCALE") or 1))
RATIO = 6.0
FLOOR = 0.05


def limit(sec):
    return sec * SCALE


def _best(f, arg, reps, stop=None):
    best = None
    for _ in range(reps):
        t0 = time.perf_counter(); f(arg); dt = time.perf_counter() - t0
        best = dt if best is None else min(best, dt)
        if stop is not None and best > stop: break   # 이미 상한 초과 — 반복 불필요
    return best


def assert_linear(tc, f, make, n, cap=1.0, reps=2):
    """f(make(n)) vs f(make(4n)) — 입력은 시간 밖에서 만든다."""
    a, b = make(n), make(4 * n)
    t1 = _best(f, a, reps, limit(cap))
    tc.assertLess(t1, limit(cap), "n=%d %.2fs > cap %.1fs" % (n, t1, limit(cap)))
    t4 = _best(f, b, reps)
    if t4 < FLOOR * SCALE: return
    tc.assertLess(t4 / max(t1, 1e-4), RATIO, "n=%d %.3fs → 4n %.3fs (×%.1f, 선형≈4·2차≈16)" % (n, t1, t4, t4 / max(t1, 1e-4)))
