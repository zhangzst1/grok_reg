"""通过 outlookmail.newcli.xyz 外部 API 获取邮箱验证码的工具类。"""
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)


class VerificationCodeError(Exception):
    """获取验证码失败时抛出。"""


class VerificationCodeFetcher:
    BASE_URL = "https://outlookmail.newcli.xyz/api/external"
    DEFAULT_API_KEY = "iZkJIHc6lZhxm63WNeTB8cSk-oL_XgR1faYXEs8I4iC9deFZOUf2TMeqzhl01pRl"
    DEFAULT_WAIT_TIMEOUT = 60
    DEFAULT_REQUEST_TIMEOUT = 100
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_RETRY_BACKOFF = 2

    _CODE_PATTERN = re.compile(r"(?<![\d-])\d{3}-\d{3}(?![\d-])")

    def __init__(self, api_key=None, request_timeout=None, session=None,
                 max_retries=None, retry_backoff=None, proxies=None, trust_env=None):
        self.api_key = api_key or self.DEFAULT_API_KEY
        self.request_timeout = request_timeout or self.DEFAULT_REQUEST_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES
        self.retry_backoff = retry_backoff if retry_backoff is not None else self.DEFAULT_RETRY_BACKOFF
        self.session = session or requests.Session()
        self.session.headers.update({"X-API-Key": self.api_key})
        # 显式指定代理时写入会话；trust_env=False 可让 requests 忽略系统/环境代理
        if proxies is not None:
            self.session.proxies.update(proxies)
        if trust_env is not None:
            self.session.trust_env = trust_env
        # 一旦发生过代理错误，则后续请求直接直连，不再走有问题的代理
        self._prefer_direct = False

    def _do_get(self, url, params, bypass_proxy=False):
        """发送单次 GET；bypass_proxy=True 时绕过系统/环境代理直连。"""
        if not bypass_proxy:
            return self.session.get(url, params=params, timeout=self.request_timeout)
        # 临时关闭环境代理读取，并显式置空 proxies，确保直连不走任何代理
        prev_trust_env = self.session.trust_env
        self.session.trust_env = False
        try:
            return self.session.get(
                url, params=params, timeout=self.request_timeout,
                proxies={"http": None, "https": None},
            )
        finally:
            self.session.trust_env = prev_trust_env

    def _get(self, url, params):
        """发送 GET 请求，遇到连接失败等临时性错误时自动重试。

        出现代理错误（ProxyError）后，后续重试会自动绕过代理直连，
        以规避本机代理（Clash/VPN 等）偶发的连接中断。
        """
        last_exc = None
        bypass_proxy = self._prefer_direct
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._do_get(url, params, bypass_proxy=bypass_proxy)
                resp.raise_for_status()
                return resp
            except requests.exceptions.HTTPError as exc:
                # 4xx（429 除外）一般重试无效，直接抛出
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status != 429 and status < 500:
                    raise
                last_exc = exc
            except requests.exceptions.ProxyError as exc:
                # 代理连不上：之后的重试改为直连，并记住本会话优先直连
                last_exc = exc
                bypass_proxy = True
                self._prefer_direct = True
            except requests.exceptions.RequestException as exc:
                # 连接失败、超时等临时性错误，重试
                last_exc = exc

            if attempt < self.max_retries:
                wait = self.retry_backoff * attempt
                logger.warning(
                    "请求 %s 失败（第 %s/%s 次）：%s，%ss 后重试%s",
                    url, attempt, self.max_retries, last_exc, wait,
                    "（绕过代理直连）" if bypass_proxy else "",
                )
                time.sleep(wait)

        logger.error("请求 %s 在 %s 次尝试后仍失败：%s", url, self.max_retries, last_exc)
        raise VerificationCodeError(f"请求 {url} 失败：{last_exc}") from last_exc

    def wait_for_message(self, email, timeout_seconds=DEFAULT_WAIT_TIMEOUT):
        url = f"{self.BASE_URL}/wait-message"
        params = {"email": email, "timeout_seconds": timeout_seconds}
        resp = self._get(url, params)
        payload = resp.json()
        data = payload.get("data") or {}
        if not data:
            raise VerificationCodeError(f"wait-message 未返回数据：{payload}")
        return data

    def get_raw_message(self, email, message_id):
        url = f"{self.BASE_URL}/messages/{message_id}/raw"
        params = {"email": email}
        resp = self._get(url, params)
        return resp.json().get("data") or {}

    @classmethod
    def extract_code(cls, text):
        if not text:
            return None
        match = cls._CODE_PATTERN.search(text)
        return match.group(0).replace("-", "") if match else None

    def fetch_code(self, email, timeout_seconds=DEFAULT_WAIT_TIMEOUT):
        logger.info("等待邮箱 %s 的验证码邮件（超时 %ss）", email, timeout_seconds)
        message = self.wait_for_message(email, timeout_seconds=timeout_seconds)
        message_id = message.get("id")
        logger.info('等待邮件 %s 成功', email)
        code = ''
        if message_id:
            logger.info("获取邮件内容 message_id=%s", message_id)
            raw = self.get_raw_message(email, message_id)
            code = self.extract_code(raw.get("raw_content"))

        if not code:
            raise VerificationCodeError(f"邮箱 {email} 未提取到验证码")

        logger.info("成功获取邮箱 %s 的验证码：%s", email, code)
        return code


if __name__ == "__main__":
    code = VerificationCodeFetcher().fetch_code("WileyGiana3362@outlook.com")
    print(code)
