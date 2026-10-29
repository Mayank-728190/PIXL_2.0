"""Real upload helper used by integration workflows, not a mocked transport."""
from io import BytesIO
from pathlib import Path

from PIL import Image


def sample_bytes(mime):
    if mime == "video/mp4":
        return Path(__file__).with_name("fixtures").joinpath("sample.mp4").read_bytes()
    output = BytesIO()
    Image.new("RGB", (64, 32), "green").save(output, {
        "image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP",
    }[mime])
    return output.getvalue()


async def uploaded_ticket(client, url, *, headers, json):
    content = sample_bytes(json["declared_mime"])
    response = await client.post(url, headers=headers, json={**json, "size_bytes": len(content)})
    assert response.status_code == 200, response.text
    upload = await client.put(response.json()["presigned_upload_url"], content=content)
    assert upload.status_code == 200, upload.text
    return response
