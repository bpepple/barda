from pathlib import Path
from typing import List, Union

import requests
from ratelimit import limits, sleep_and_retry

from barda import exceptions

ONE_MINUTE = 60


class PostData:
    def __init__(self, user: str, passwd: str) -> None:
        self.user = user
        self.passwd = passwd
        self.api_url = "http://127.0.0.1:8000/api/{}/"

    def _post(self, endpoint: List[Union[str, int]], data):
        url = self.api_url.format("/".join(str(e) for e in endpoint))
        resp = self._request_post_data(url, data)
        if "detail" in resp:
            raise exceptions.ApiError(resp["detail"])
        return resp

    @sleep_and_retry
    @limits(calls=25, period=ONE_MINUTE)
    def _request_post_data(self, url: str, data):
        if "image" in data.keys():
            i = data.pop("image")
            img_path = Path(i)
            files = {"image": (img_path.name, img_path.open(mode="rb"))}
        else:
            i = None
            files = None

        try:
            response = requests.post(
                url, auth=(self.user, self.passwd), data=data, files=files
            )
        except requests.exceptions.ConnectionError as e:
            raise exceptions.ApiError(f"Connection error: {repr(e)}") from e

        if response.status_code == 400:
            raise exceptions.ApiError(f"Bad request. data={data}, image={i}")

        return response.json()

    def post_arc(self, data):
        return self._post(["arc"], data)

    def post_character(self, data):
        return self._post(["character"], data)

    def post_creator(self, data):
        return self._post(["creator"], data)

    def post_issue(self, data):
        return self._post(["issue"], data)

    def post_series(self, data):
        return self._post(["series"], data)

    def post_team(self, data):
        return self._post(["team"], data)
