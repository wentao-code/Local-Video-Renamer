import unittest

from app.scraper.binghuo_actor_scraper import BinghuoActorScraper


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    def inner_text(self, timeout=None):
        return self._text


class _FakePage:
    def __init__(self, url, body_text):
        self.url = url
        self._body_text = body_text

    def locator(self, selector):
        if selector != 'body':
            raise AssertionError(f'unexpected selector: {selector}')
        return _FakeLocator(self._body_text)


class BinghuoActorScraperParseProfileTest(unittest.TestCase):
    def test_parse_profile_accepts_non_zero_padded_birthday_and_colon_measurements(self):
        page = _FakePage(
            'https://www.fouroursonsinc.com/person/2392',
            '\n'.join(
                [
                    '生日：',
                    '2001-4-30',
                    '年龄：',
                    '25',
                    '身高：',
                    '152cm',
                    '三围：',
                    'B:80(C) W:56 H:84',
                ]
            ),
        )

        profile = BinghuoActorScraper().parse_profile(page)

        self.assertEqual(profile['person_id'], '2392')
        self.assertEqual(profile['birthday'], '2001-04-30')
        self.assertEqual(profile['age'], '25')
        self.assertEqual(profile['height'], '152')
        self.assertEqual(profile['bust'], '80')
        self.assertEqual(profile['waist'], '56')
        self.assertEqual(profile['hip'], '84')

    def test_parse_profile_accepts_measurements_with_axis_prefixes(self):
        page = _FakePage(
            'https://www.fouroursonsinc.com/person/1000',
            'B86 / W58 / H87',
        )

        profile = BinghuoActorScraper().parse_profile(page)

        self.assertEqual(profile['bust'], '86')
        self.assertEqual(profile['waist'], '58')
        self.assertEqual(profile['hip'], '87')

    def test_parse_profile_accepts_dash_separated_measurements(self):
        page = _FakePage(
            'https://www.fouroursonsinc.com/person/1001',
            '90-64-90(cm)',
        )

        profile = BinghuoActorScraper().parse_profile(page)

        self.assertEqual(profile['bust'], '90')
        self.assertEqual(profile['waist'], '64')
        self.assertEqual(profile['hip'], '90')

    def test_parse_profile_accepts_measurements_with_cup_and_cm_suffix(self):
        page = _FakePage(
            'https://www.fouroursonsinc.com/person/1002',
            'B101cm (J) W59cm H91cm',
        )

        profile = BinghuoActorScraper().parse_profile(page)

        self.assertEqual(profile['bust'], '101')
        self.assertEqual(profile['waist'], '59')
        self.assertEqual(profile['hip'], '91')


if __name__ == '__main__':
    unittest.main()
