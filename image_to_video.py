import sys
import higgsfield_client

image_url = sys.argv[1]

print("Sending request to Higgsfield... please wait ⏳")

result = higgsfield_client.subscribe(
    'higgsfield/dop/v1/image-to-video',
    arguments={
        'model': 'dop-turbo',
        'prompt': 'Cinematic camera movement',
        'input_images': [{'type': 'image_url', 'image_url': image_url}],
    }
)

print("\nRaw response:")
print(result)

print("\n✅ Done! Here is your video URL:")
print(result['videos'][0]['url'])
