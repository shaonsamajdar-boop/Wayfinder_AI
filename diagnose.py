"""Interactive provider check. Does not print credentials."""
import asyncio
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env', override=True)
import services

async def main():
    print('Wayfinder AI — connection diagnostics (keys are never printed)')
    for name in ('GEMINI_API_KEY', 'GEOAPIFY_API_KEY'):
        print(f'{name}:', 'configured' if services.configured(name) else 'MISSING / PLACEHOLDER')
    if services.configured('GEMINI_API_KEY'):
        result = await services.ai_status(probe=True)
        print('Gemini test:', 'SUCCESS' if result['available'] else 'FAILED')
        print('Working model:', result['model'] or '(none)')
        print('Details:', result['detail'])
        if not result['available']:
            print('Check the Gemini key in Google AI Studio and its free-tier project availability.')
    if services.configured('GEOAPIFY_API_KEY'):
        try:
            places = await services.geocode('Kolkata, India')
            print('Geoapify geocode:', 'SUCCESS' if places else 'No results')
        except services.ProviderError as exc:
            print('Geoapify error:', exc.status, str(exc))

if __name__ == '__main__':
    asyncio.run(main())
