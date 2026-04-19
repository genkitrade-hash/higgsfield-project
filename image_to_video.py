import sys
import higgsfield_client

image_url = sys.argv[1]
prompt = sys.argv[2] if len(sys.argv) > 2 else "Cinematic camera movement"

print("Sending request to Higgsfield... please wait ⏳")

result = higgsfield_client.subscribe(
    'higgsfield-ai/dop/lite',
    arguments={
        'prompt': prompt,
        'input_images': [{'type': 'image_url', 'image_url': image_url}],
        'motions': [],
        'enhance_prompt': True,
    }
)

print("\nRaw response:")
print(result)

print("\n✅ Done! Here is your video URL:")
print(result['videos'][0]['url'])
