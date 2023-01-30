from pathlib import Path
from typing import List, Union

import requests
from ratelimit import limits, sleep_and_retry
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from barda import exceptions

ONE_MINUTE = 60


class PostData:
    def __init__(self, user: str, passwd: str) -> None:
        self.user = user
        self.passwd = passwd
        self.api_url = "http://127.0.0.1:8000/api/{}/"

    @sleep_and_retry
    @limits(calls=30, period=ONE_MINUTE)
    def _post(self, endpoint: List[Union[str, int]], data):
        url = self.api_url.format("/".join(str(e) for e in endpoint))

        if "image" in data.keys():
            i = data.pop("image")
            img_path = Path(i)
            files = {"image": (img_path.name, img_path.open(mode="rb"))}
        else:
            i = None
            files = None

        try:
            session = requests.Session()
            retry = Retry(connect=3, backoff_factor=0.5)
            session.mount("https://", HTTPAdapter(max_retries=retry))
            response = session.post(
                url, timeout=2.5, auth=(self.user, self.passwd), data=data, files=files
            )
        except requests.exceptions.ConnectionError as e:
            raise exceptions.ApiError(f"Connection error: {repr(e)}") from e

        if response.status_code == 400:
            raise exceptions.ApiError(f"Bad request. data={data}, image={i}")

        resp = response.json()
        if "detail" in resp:
            raise exceptions.ApiError(resp["detail"])
        return resp

    def post_arc(self, data):
        return self._post(["arc"], data)

    def post_character(self, data):
        return self._post(["character"], data)

    def post_creator(self, data):
        return self._post(["creator"], data)

    def post_credit(self, data):
        return self._post(["credit"], data)

    def post_issue(self, data):
        return self._post(["issue"], data)

    def post_series(self, data):
        return self._post(["series"], data)

    def post_team(self, data):
        return self._post(["team"], data)
