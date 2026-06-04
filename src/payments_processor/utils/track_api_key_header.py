from fastapi import Header


def track_api_key_header(x_api_key: str = Header(...)) -> None:
    _ = x_api_key
