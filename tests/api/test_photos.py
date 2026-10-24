from conferge.api.photos import ImageMeta, image_format


def test_photo_meta_requires_linkedin_profile_image():
    parser = ImageMeta()
    parser.feed('<meta property="og:image" content="https://media.licdn.com/dms/profile-displayphoto/a.jpg?x=1&amp;y=2">')
    assert parser.url == 'https://media.licdn.com/dms/profile-displayphoto/a.jpg?x=1&y=2'
    for url in ['http://media.licdn.com/profile-displayphoto/a.jpg', 'https://evil.test/profile-displayphoto/a.jpg',
                'https://media.licdn.com/company-logo/a.jpg', 'https://media.licdn.com.evil.test/profile-displayphoto/a.jpg']:
        parser = ImageMeta()
        parser.feed(f'<meta property="og:image" content="{url}">')
        assert parser.url is None


def test_photo_response_must_be_image_not_html():
    assert image_format(b'<html>Access denied</html>') is None
    assert image_format(b'\xff\xd8\xffdata') == ('.jpg', 'image/jpeg')
    assert image_format(b'\x89PNG\r\n\x1a\n') == ('.png', 'image/png')
