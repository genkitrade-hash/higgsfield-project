import sys
import higgsfield_client

image_url = sys.argv[1]

print("Sending request to Higgsfield... please wait ⏳")

result = higgsfield_client.subscribe(
    'bytedance/seedance/v1/image-to-video',
    arguments={
        'image_url': image_url,
        'duration': 5,
        'resolution': '1080p',
        'aspect_ratio': '16:9',
    }
)

print("\n✅ Done! Here is your video URL:")
print(result['video']['url'])
