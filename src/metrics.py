from prometheus_client import Counter, Histogram, Gauge

# Counters
CAPTCHA_REQUESTS_TOTAL = Counter(
    'captcha_requests_total',
    'Total number of CAPTCHA solve requests',
    ['captcha_type', 'status']  # status: success, failure, rate_limited
)

CAPTCHA_FALLBACKS_TOTAL = Counter(
    'captcha_fallbacks_total',
    'Total number of times a fallback solver was used (e.g. audio to image)',
    ['captcha_type', 'fallback_reason']
)

CAPTCHA_RATE_LIMITS_TOTAL = Counter(
    'captcha_rate_limits_total',
    'Total number of rate limits encountered per proxy',
    ['proxy_ip']
)

# Histograms
CAPTCHA_SOLVE_DURATION_SECONDS = Histogram(
    'captcha_solve_duration_seconds',
    'Time spent solving a CAPTCHA',
    ['captcha_type', 'solver_method'],  # solver_method: audio, image, fast_token
    buckets=[1.0, 3.0, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0]
)

# Gauges
ACTIVE_SOLVES = Gauge(
    'captcha_active_solves',
    'Number of currently active CAPTCHA solve tasks'
)
