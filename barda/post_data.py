import json
import platform
from logging import getLogger
from pathlib import Path
from typing import List, Union

import requests
from ratelimit import limits, sleep_and_retry
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from barda import __version__, exceptions

LOGGER = getLogger(__name__)

ONE_MINUTE = 60


class PostData:
    def __init__(self, user: str, passwd: str) -> None:
        self.user = user
        self.passwd = passwd
        self.api_url = "https://metron.cloud/api/{}/"
        self.header = {
            "User-Agent": f"Barda/{__version__} ({platform.system()}; {platform.release()})"
        }

    @sleep_and_retry
    @limits(calls=30, period=ONE_MINUTE)
    def _post(self, endpoint: List[Union[str, int]], data):
        url = self.api_url.format("/".join(str(e) for e in endpoint))

        if "image" in data.keys():
            i = data.pop("image")
            if i:
                img_path = Path(i)
                files = {"image": (img_path.name, img_path.read_bytes())}
            else:
                files = None
        else:
            i = ""
            files = None

        LOGGER.debug(f"post() data: {data}")
        try:
            session = requests.Session()
            retry = Retry(connect=3, backoff_factor=0.5)
            session.mount("https://", HTTPAdapter(max_retries=retry))
            response = session.post(
                url,
                timeout=40,
                headers=self.header,
                auth=(self.user, self.passwd),
                data=data,
                files=files,
            )
        except requests.exceptions.ConnectionError as e:
            LOGGER.error(f"Connection error: {repr(e)}")
            raise exceptions.ApiError(f"Connection error: {repr(e)}") from e

        if response.status_code == 400:
            LOGGER.error(f"Bad Request: data={data}, image={i}")
            raise exceptions.ApiError(f"Bad request. data={data}, image={i}")

        resp = response.json()
        if "detail" in resp:
            LOGGER.error(f"Server Error: {resp['detail']}")
            raise exceptions.ApiError(resp["detail"])
        return resp

    @sleep_and_retry
    @limits(calls=20, period=ONE_MINUTE)
    def _post_credits(self, endpoint: List[Union[str, int]], data):
        url = self.api_url.format("/".join(str(e) for e in endpoint))

        header = {
            "User-Agent": f"Barda/{__version__} ({platform.system()}; {platform.release()})",
            "Content-Type": "application/json",
        }

        LOGGER.debug(f"post_credits data: {data}")

        try:
            session = requests.Session()
            retry = Retry(connect=3, backoff_factor=0.5)
            session.mount("https://", HTTPAdapter(max_retries=retry))
            response = session.post(
                url,
                timeout=40,
                headers=header,
                auth=(self.user, self.passwd),
                data=json.dumps(data),
            )
        except requests.exceptions.ConnectionError as e:
            LOGGER.error(f"Connection error: {repr(e)}")
            raise exceptions.ApiError(f"Connection error: {repr(e)}") from e

        if response.status_code == 400:
            LOGGER.error(f"Bad Request: data={data}")
            raise exceptions.ApiError(f"Bad request. data={data}")

        resp = response.json()
        if "detail" in resp:
            LOGGER.error(f"Server Error: {resp['detail']}")
            raise exceptions.ApiError(resp["detail"])
        return resp

    @sleep_and_retry
    @limits(calls=8, period=ONE_MINUTE)
    def _patch(self, endpoint: List[Union[str, int]], data):
        url = self.api_url.format("/".join(str(e) for e in endpoint))

        LOGGER.debug(f"patch() data: {data}")
        try:
            session = requests.Session()
            retry = Retry(connect=3, backoff_factor=0.5)
            session.mount("https://", HTTPAdapter(max_retries=retry))
            response = session.patch(
                url,
                timeout=40,
                headers=self.header,
                auth=(self.user, self.passwd),
                data=data,
            )
        except requests.exceptions.ConnectionError as e:
            LOGGER.error(f"Connection error: {repr(e)}")
            raise exceptions.ApiError(f"Connection error: {repr(e)}") from e

        if response.status_code == 400:
            LOGGER.error(f"Bad Request: data={data}")
            raise exceptions.ApiError(f"Bad request. data={data}")

        resp = response.json()
        if "detail" in resp:
            LOGGER.error(f"Server Error: {resp['detail']}")
            raise exceptions.ApiError(resp["detail"])
        return resp

    def patch_arc(self, id_: int, data):
        return self._patch(["arc", id_], data)

    def post_arc(self, data):
        return self._post(["arc"], data)

    def patch_character(self, id_: int, data):
        return self._patch(["character", id_], data)

    def post_character(self, data):
        return self._post(["character"], data)

    def patch_creator(self, id_: int, data):
        return self._patch(["creator", id_], data)

    def post_creator(self, data):
        return self._post(["creator"], data)

    def post_credit(self, data):
        return self._post_credits(["credit"], data)

    def patch_issue(self, id_: int, data):
        return self._patch(["issue", id_], data)

    def post_issue(self, data):
        return self._post(["issue"], data)

    def patch_series(self, id_: int, data):
        return self._patch(["series", id_], data)

    def post_series(self, data):
        return self._post(["series"], data)

    def patch_team(self, id_: int, data):
        return self._patch(["team", id_], data)

    def post_team(self, data):
        return self._post(["team"], data)
