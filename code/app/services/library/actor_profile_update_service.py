from datetime import date

from app.core.actor_profile_display import UNKNOWN_ACTOR_AGE_TEXT
from app.services.identity import is_ignored_actor_name, normalize_actor_name


DEFAULT_BIRTHDAY_MONTH = 7
DEFAULT_BIRTHDAY_DAY = 18
_UNKNOWN_BIRTHDAY_VALUES = {'暂无', '未知'}
_UNKNOWN_AGE_VALUES = {'暂无', '未知', UNKNOWN_ACTOR_AGE_TEXT}


class ActorProfileUpdateService:
    def normalize_payload(self, name, birthday='', age='', today=None):
        normalized_name = normalize_actor_name(name)
        if not normalized_name:
            raise ValueError('演员名称不能为空')
        if is_ignored_actor_name(normalized_name):
            raise ValueError('这个演员名称不可用')

        reference_day = today or date.today()
        normalized_birthday = self._normalize_birthday_text(birthday)
        normalized_age = self._normalize_age_text(age)

        if normalized_birthday and not normalized_age:
            normalized_age = str(self._calculate_age_from_birthday(normalized_birthday, today=reference_day))
        elif normalized_age and not normalized_birthday:
            normalized_birthday = self._build_default_birthday_for_age(normalized_age, today=reference_day)
        elif normalized_birthday and normalized_age:
            calculated_age = str(self._calculate_age_from_birthday(normalized_birthday, today=reference_day))
            if calculated_age != normalized_age:
                normalized_age = calculated_age

        return {
            'name': normalized_name,
            'birthday': normalized_birthday,
            'age': normalized_age,
        }

    @classmethod
    def _normalize_birthday_text(cls, value):
        text = str(value or '').strip()
        if not text or text in _UNKNOWN_BIRTHDAY_VALUES:
            return ''
        try:
            parsed = cls._parse_birthday_date(text)
        except ValueError as exc:
            raise ValueError('生日格式必须为 YYYY-MM-DD 或 YYYY/M/D') from exc
        return parsed.isoformat()

    @staticmethod
    def _normalize_age_text(value):
        text = str(value or '').strip()
        if not text or text in _UNKNOWN_AGE_VALUES:
            return ''
        if not text.isdigit():
            raise ValueError('年龄必须为非负整数')
        return str(int(text))

    @staticmethod
    def _parse_birthday_date(value):
        text = str(value or '').strip()
        if '/' in text:
            year_text, month_text, day_text = text.split('/')
            return date(int(year_text), int(month_text), int(day_text))
        return date.fromisoformat(text)

    @staticmethod
    def _calculate_age_from_birthday(birthday_text, today=None):
        birthday = date.fromisoformat(str(birthday_text))
        reference_day = today or date.today()
        age = reference_day.year - birthday.year
        if (reference_day.month, reference_day.day) < (birthday.month, birthday.day):
            age -= 1
        return max(age, 0)

    @classmethod
    def _build_default_birthday_for_age(cls, age_text, today=None):
        reference_day = today or date.today()
        age_value = int(age_text)
        birth_year = reference_day.year - age_value
        if (reference_day.month, reference_day.day) < (DEFAULT_BIRTHDAY_MONTH, DEFAULT_BIRTHDAY_DAY):
            birth_year -= 1
        return date(birth_year, DEFAULT_BIRTHDAY_MONTH, DEFAULT_BIRTHDAY_DAY).isoformat()
