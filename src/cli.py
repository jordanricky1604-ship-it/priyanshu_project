from __future__ import annotations

import asyncio
import functools
import sys
from typing import Any, Callable, Coroutine, Optional

import click

from src.config import AppConfig, SolverConfig, get_config, save_config
from src.utils.logging import setup_logging
from src.models import CaptchaType
from src.profiles import ProfileManager
from src.router import StrategyRouter
from src.browser import get_browser, close_browser
from src.daemon import run_daemon


def async_command(f: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Any]:
    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))
    return wrapper


CAPTCHA_TYPE_MAP = {
    "image": CaptchaType.IMAGE_CAPTCHA,
    "recaptcha-v2": CaptchaType.RECAPTCHA_V2,
    "recaptcha-v2-invisible": CaptchaType.RECAPTCHA_V2_INVISIBLE,
    "recaptcha-v3": CaptchaType.RECAPTCHA_V3,
    "recaptcha-enterprise": CaptchaType.RECAPTCHA_ENTERPRISE,
    "hcaptcha": CaptchaType.HCAPTCHA,
    "hcaptcha-invisible": CaptchaType.HCAPTCHA_INVISIBLE,
    "turnstile": CaptchaType.TURNSTILE,
    "funcaptcha": CaptchaType.FUNCAPTCHA,
    "geetest": CaptchaType.GEETEST_V3,
    "aws": CaptchaType.AWS_WAF,
    "auto": None,
}


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--config", "config_path", type=click.Path(), help="Config file path")
@click.pass_context
def cli(ctx: click.Context, debug: bool, config_path: Optional[str]) -> None:
    setup_logging("DEBUG" if debug else "INFO")
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@cli.command()
@click.option("--url", "-u", required=True, help="Target page URL")
@click.option("--type", "-t", "captcha_type", default="auto",
              type=click.Choice(list(CAPTCHA_TYPE_MAP.keys())),
              help="Force specific captcha type")
@click.option("--profile", "-p", default="default", help="Browser profile name")
@click.option("--proxy", "-x", default=None, help="Proxy URL (e.g. socks5://user:pass@host:port)")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@async_command
async def solve(
    url: str,
    captcha_type: str,
    profile: str,
    proxy: Optional[str],
    headless: bool,
) -> None:
    """Detect and solve a CAPTCHA on a webpage."""
    config = get_config()
    if headless:
        config.solver.browser_headless = True
    if proxy:
        from src.config import ProxyConfig

        pm = ProfileManager()
        profile_obj = pm.get_or_create(profile)
        profile_obj.proxy = ProxyConfig(server=proxy)
        config.add_profile(profile_obj)
        save_config()

    force_type = CAPTCHA_TYPE_MAP[captcha_type]
    type_label = force_type.name if force_type else "auto-detect"
    click.echo(f"Solving CAPTCHA at {url} (type: {type_label}, profile: {profile})")

    try:
        browser = await get_browser(config.solver)
        pm = ProfileManager()
        router = StrategyRouter(config.solver, browser, pm)
        solution = await router.solve(url, profile_name=profile, force_type=force_type)

        if solution.success:
            click.echo(f"\nSolved ({solution.solved_via}, {solution.elapsed_ms:.0f}ms, {solution.attempts} attempts)")
            click.echo(f"Token: {solution.token[:80]}{'...' if len(solution.token) > 80 else ''}")
        else:
            click.echo(f"\nFailed: {solution.error}", err=True)
            sys.exit(1)
    finally:
        await close_browser()


@cli.command()
@click.option("--url", "-u", required=True, help="Target page URL")
@async_command
async def detect(url: str) -> None:
    """Detect CAPTCHA type without solving."""
    from src.detector import detect_captcha

    config = get_config()
    browser = await get_browser(config.solver)
    try:
        from src.browser import create_context

        async with create_context(browser) as context:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3.0)
            challenge = await detect_captcha(page, url)
            click.echo(f"Type: {challenge.type.name}")
            click.echo(f"Sitekey: {challenge.sitekey or 'N/A'}")
            click.echo(f"Action: {challenge.action or 'N/A'}")
            click.echo(f"Invisible: {challenge.is_invisible}")
            click.echo(f"Extra: {challenge.extra}")
    finally:
        await close_browser()


@cli.group()
def profiles() -> None:
    """Manage browser profiles."""


@profiles.command("list")
@async_command
async def profiles_list() -> None:
    """List all browser profiles."""
    pm = ProfileManager()
    for p in pm.list():
        click.echo(f"  {p.name}: dir={p.user_data_dir}, uses={p.use_count}, success_rate={p.success_count/max(p.use_count,1)*100:.0f}%")


@profiles.command("create")
@click.option("--name", "-n", required=True, help="Profile name")
@click.option("--proxy", "-x", default=None, help="Proxy for this profile")
@async_command
async def profiles_create(name: str, proxy: Optional[str]) -> None:
    """Create a new browser profile."""
    from src.config import ProxyConfig

    proxy_cfg = ProxyConfig(server=proxy) if proxy else None
    pm = ProfileManager()
    profile = pm.create(name, proxy=proxy_cfg)
    click.echo(f"Created profile '{profile.name}' at {profile.user_data_dir}")
@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8000, help="Port to bind to")
def daemon(host: str, port: int) -> None:
    run_daemon(host, port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
