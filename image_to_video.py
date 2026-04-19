import sys
import higgsfield_client

image_url = sys.argv[1]

print("Sending request to Higgsfield... please wait ⏳")

result = higgsfield_client.subscribe(
    '/v1/image2video/dop',
    arguments={
        'model': 'dop-turbo',
        'prompt': 'Cinematic camera movement',
        'input_images': [{'type': 'image_url', 'image_url': image_url}],
    }
)

print("\n✅ Done! Here is your video URL:")
print(result['videos'][0]['url'])
