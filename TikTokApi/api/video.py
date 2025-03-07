from __future__ import annotations

from venv import logger

from requests import request

from ..helpers import extract_video_id_from_url, requests_cookie_to_playwright_cookie
from typing import TYPE_CHECKING, ClassVar, Iterator, Optional
from datetime import datetime
import requests
from ..exceptions import InvalidResponseException
import json
import httpx
from typing import Union, AsyncIterator

if TYPE_CHECKING:
    from ..tiktok import TikTokApi
    from .user import User
    from .sound import Sound
    from .hashtag import Hashtag
    from .comment import Comment


class Video:
    """
    A TikTok Video class

    Example Usage
    ```py
    video = api.video(id='7041997751718137094')
    ```
    """

    parent: ClassVar[TikTokApi]

    id: Optional[str]
    """TikTok's ID of the Video"""
    url: Optional[str]
    """The URL of the Video"""
    create_time: Optional[datetime]
    """The creation time of the Video"""
    stats: Optional[dict]
    """TikTok's stats of the Video"""
    author: Optional[User]
    """The User who created the Video"""
    sound: Optional[Sound]
    """The Sound that is associated with the Video"""
    hashtags: Optional[list[Hashtag]]
    """A List of Hashtags on the Video"""
    as_dict: dict
    """The raw data associated with this Video."""

    def __init__(
        self,
        id: Optional[str] = None,
        url: Optional[str] = None,
        data: Optional[dict] = None,
        **kwargs,
    ):
        """
        You must provide the id or a valid url, else this will fail.
        """
        self.id = id
        self.url = url
        if data is not None:
            self.as_dict = data
            self.__extract_from_data()
        elif url is not None:
            i, session = self.parent._get_session(**kwargs)
            self.id = extract_video_id_from_url(
                url,
                headers=session.headers,
                proxy=kwargs.get("proxy")
                if kwargs.get("proxy") is not None
                else session.proxy,
            )

        if getattr(self, "id", None) is None:
            raise TypeError("You must provide id or url parameter.")

    async def info(self, **kwargs) -> dict:
        """
        Returns a dictionary of all data associated with a TikTok Video.

        Note: This is slow since it requires an HTTP request, avoid using this if possible.

        Returns:
            dict: A dictionary of all data associated with a TikTok Video.

        Raises:
            InvalidResponseException: If TikTok returns an invalid response, or one we don't understand.

        Example Usage:
            .. code-block:: python

                url = "https://www.tiktok.com/@davidteathercodes/video/7106686413101468970"
                video_info = await api.video(url=url).info()
        """
        i, session = self.parent._get_session(**kwargs)
        proxy = (
            kwargs.get("proxy") if kwargs.get("proxy") is not None else session.proxy
        )
        if self.url is None:
            raise TypeError("To call video.info() you need to set the video's url.")

        r = requests.get(self.url, headers=session.headers, proxies=proxy)
        if r.status_code != 200:
            raise InvalidResponseException(
                r.text, "TikTok returned an invalid response.", error_code=r.status_code
            )

        # Try SIGI_STATE first
        # extract tag <script id="SIGI_STATE" type="application/json">{..}</script>
        # extract json in the middle

        start = r.text.find('<script id="SIGI_STATE" type="application/json">')
        if start != -1:
            start += len('<script id="SIGI_STATE" type="application/json">')
            end = r.text.find("</script>", start)

            if end == -1:
                raise InvalidResponseException(
                    r.text, "TikTok returned an invalid response.", error_code=r.status_code
                )

            data = json.loads(r.text[start:end])
            video_info = data["ItemModule"][self.id]
        else:
            # Try __UNIVERSAL_DATA_FOR_REHYDRATION__ next

            # extract tag <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{..}</script>
            # extract json in the middle

            start = r.text.find('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">')
            if start == -1:
                raise InvalidResponseException(
                    r.text, "TikTok returned an invalid response.", error_code=r.status_code
                )

            start += len('<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">')
            end = r.text.find("</script>", start)

            if end == -1:
                raise InvalidResponseException(
                    r.text, "TikTok returned an invalid response.", error_code=r.status_code
                )

            data = json.loads(r.text[start:end])
            default_scope = data.get("__DEFAULT_SCOPE__", {})
            video_detail = default_scope.get("webapp.video-detail", {})
            if video_detail.get("statusCode", 0) != 0: # assume 0 if not present
                raise InvalidResponseException(
                    r.text, "TikTok returned an invalid response structure.", error_code=r.status_code
                )
            video_info = video_detail.get("itemInfo", {}).get("itemStruct")
            if video_info is None:
                raise InvalidResponseException(
                    r.text, "TikTok returned an invalid response structure.", error_code=r.status_code
                )
            
        self.as_dict = video_info
        self.__extract_from_data()

        cookies = [requests_cookie_to_playwright_cookie(c) for c in r.cookies]

        await self.parent.set_session_cookies(
            session, 
            cookies
        )
        return video_info

    async def bytes(self, stream: bool = False, **kwargs) -> Union[bytes, AsyncIterator[bytes]]:
        """
        Returns the bytes of a TikTok Video.

        TODO:
            Not implemented yet.

        Example Usage:
            .. code-block:: python

                video_bytes = await api.video(id='7041997751718137094').bytes()

                # Saving The Video
                with open('saved_video.mp4', 'wb') as output:
                    output.write(video_bytes)

                # Streaming (if stream=True)
                async for chunk in api.video(id='7041997751718137094').bytes(stream=True):
                    # Process or upload chunk
        """
        i, session = self.parent._get_session(**kwargs)

        urls = extract_url_lists(self.as_dict)

        cookies = await self.parent.get_session_cookies(session)

        h = session.headers
        h["range"] = 'bytes=0-'
        h["accept-encoding"] = 'identity;q=1, *;q=0'
        h["referer"] = 'https://www.tiktok.com/'
        logger.debug(f'Cookies for request: \n {cookies}')
        if stream:
            for url in urls:
                logger.info(f'Attempting stream download from URL: {url}')
                try:
                    async def stream_bytes():
                        async with httpx.AsyncClient() as client:
                            async with client.stream('GET', url, headers=h, cookies=cookies) as streamedResponse:
                                logger.debug("Attempting to read streamed response before accessing")
                                await streamedResponse.aread()
                                if streamedResponse.status_code != 200:
                                    raise InvalidResponseException(
                                        f"Error streaming:",
                                        f"StatusCode {streamedResponse.status_code} \n download uri: {url}"
                                    )
                                # Peek at the first chunk
                                logger.debug("Checking response first chunk")
                                first_chunk = b""
                                async for chunk in streamedResponse.aiter_bytes():
                                    first_chunk = chunk
                                    break  # Get only the first chunk

                                if not first_chunk or b'ftyp' not in first_chunk[:32]:
                                    logger.error("Invalid first chunk not video")
                                    return  # Exit the generator without yielding

                                logger.info('first_chunk validated OK. Yielding stream.')
                                yield first_chunk  # Yield the validated first chunk

                                # Continue yielding the rest of the stream
                                async for chunk in streamedResponse.aiter_bytes():
                                    yield chunk

                    # Consume the generator to check the first chunk:
                    gen = stream_bytes()
                    try:
                        first = await gen.__anext__()
                    except StopAsyncIteration:
                        # This URL did not yield valid data; move on to the next one.
                        logger.error(f"No valid data yielded from URL: {url}")
                        continue

                    # If we got here, the first chunk is valid. Create a new generator that yields the first chunk then the rest.
                    async def valid_stream_generator(first_chunk, gen):
                        yield first_chunk
                        async for chunk in gen:
                            yield chunk

                    # Return the valid generator
                    return valid_stream_generator(first, gen)
                except Exception as e:
                    logger.error(f"An error occurred while streaming URL: {url} \n {e}")
                    continue  # Move on to the next URL

        else:
            for url in urls:
                logger.info(f'Attempting standard download from URL:{url}')
                try:
                    response = requests.get(url, headers=h, cookies=cookies)
                    if response.status_code == 200 and "video" in response.headers.get("Content-Type", ""):
                        # Validate content before returning
                        if not response.content or b'ftyp' not in response.content[:32]:
                            raise StopIteration("Invalid video detected") ##onto the next url

                        return response.content
                    else:
                        raise InvalidResponseException(
                                        f"Error downloading:",f"StatusCode {response.status_code} \n Content: {response.content} download uri: {url}")
                except Exception as e:
                    logger.error(f"An error occurred while processing url: {url} \n {e}")
                    continue  # Move on to the next URL

    def __extract_from_data(self) -> None:
        data = self.as_dict
        self.id = data["id"]

        timestamp = data.get("createTime", None)
        if timestamp is not None:
            try:
                timestamp = int(timestamp)
            except ValueError:
                pass

        self.create_time = datetime.fromtimestamp(timestamp)
        self.stats = data.get('statsV2') or data.get('stats')

        author = data.get("author")
        if isinstance(author, str):
            self.author = self.parent.user(username=author)
        else:
            self.author = self.parent.user(data=author)
        self.sound = self.parent.sound(data=data)

        self.hashtags = [
            self.parent.hashtag(data=hashtag) for hashtag in data.get("challenges", [])
        ]

        self.url = f"https://www.tiktok.com/@{self.author}/video/{self.id}"

        if getattr(self, "id", None) is None:
            Video.parent.logger.error(
                f"Failed to create Video with data: {data}\nwhich has keys {data.keys()}"
            )

    async def comments(self, count=20, cursor=0, **kwargs) -> Iterator[Comment]:
        """
        Returns the comments of a TikTok Video.

        Parameters:
            count (int): The amount of comments you want returned.
            cursor (int): The the offset of comments from 0 you want to get.

        Returns:
            async iterator/generator: Yields TikTokApi.comment objects.

        Example Usage
        .. code-block:: python

            async for comment in api.video(id='7041997751718137094').comments():
                # do something
        ```
        """
        found = 0
        while found < count:
            params = {
                "aweme_id": self.id,
                "count": 20,
                "cursor": cursor,
            }

            resp = await self.parent.make_request(
                url="https://www.tiktok.com/api/comment/list/",
                params=params,
                headers=kwargs.get("headers"),
                session_index=kwargs.get("session_index"),
            )

            if resp is None:
                raise InvalidResponseException(
                    resp, "TikTok returned an invalid response."
                )

            for video in resp.get("comments", []):
                yield self.parent.comment(data=video)
                found += 1

            if not resp.get("has_more", False):
                return

            cursor = resp.get("cursor")

    async def related_videos(
        self, count: int = 30, cursor: int = 0, **kwargs
    ) -> Iterator[Video]:
        """
        Returns related videos of a TikTok Video.

        Parameters:
            count (int): The amount of comments you want returned.
            cursor (int): The the offset of comments from 0 you want to get.

        Returns:
            async iterator/generator: Yields TikTokApi.video objects.

        Example Usage
        .. code-block:: python

            async for related_videos in api.video(id='7041997751718137094').related_videos():
                # do something
        ```
        """
        found = 0
        while found < count:
            params = {
                "itemID": self.id,
                "count": 16,
            }

            resp = await self.parent.make_request(
                url="https://www.tiktok.com/api/related/item_list/",
                params=params,
                headers=kwargs.get("headers"),
                session_index=kwargs.get("session_index"),
            )

            if resp is None:
                raise InvalidResponseException(
                    resp, "TikTok returned an invalid response."
                )

            for video in resp.get("itemList", []):
                yield self.parent.video(data=video)
                found += 1

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f"TikTokApi.video(id='{getattr(self, 'id', None)}')"

def extract_url_lists(data):
    """
    Recursively extracts all strings from 'UrlList' keys in a nested dictionary.
    :param data: The dictionary to search through
    :return: A list of strings from all 'UrlList' keys
    """
    urls = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key == "downloadAddr" and isinstance(value, str):
                urls.append(value)
            # elif key == "UrlList" and isinstance(value, list):
            #     urls.extend(value)  # Add strings in 'UrlList' to the result
            # elif key == "PlayAddr" and isinstance(value, list):
            #     urls.extend(value)  # Add strings in 'UrlList' to the result

            else:
                urls.extend(extract_url_lists(value))  # Recurse into sub-dictionaries or lists
    elif isinstance(data, list):
        for item in data:
            urls.extend(extract_url_lists(item))  # Recurse into list elements

    return urls