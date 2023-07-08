import logging
import re
from decimal import Decimal, InvalidOperation
from enum import Enum, unique

import questionary

LOGGER = logging.getLogger(__name__)


@unique
class Rating(Enum):
    Unknown = 1
    Everyone = 2
    Teen = 3
    Teen_Plus = 4
    Mature = 5
    CCA = 6


class GCD_Issue:
    def __init__(
        self,
        gcd_id: int,
        number: str,
        price: str = "",
        pages: Decimal = Decimal("0.00"),
        rating: str = "",
        barcode: str = "",
        publisher: int = 0,
    ) -> None:
        self.id: int = gcd_id
        self.publisher: int = publisher
        self.number: str = self.set_number(number)
        self.price: Decimal | None = self.set_price(price)
        self.barcode: str | None = self.set_barcode(barcode)
        self.pages: int | None = self.set_page(pages)
        self.rating: int = self.set_rating(rating)

    def _choose_rating(self, wrong: str) -> int:
        choices = []
        for i in Rating:
            choice = questionary.Choice(title=i.name, value=i.value)
            choices.append(choice)
        return questionary.select(
            f"Unable to find '{wrong}'. What should the ratings be?", choices=choices
        ).ask()

    def set_rating(self, rating: str) -> int:
        if not rating:
            return Rating.Unknown.value

        MARVEL = [31, 16, 26, 78, 265, 1217, 401]
        if self.publisher in MARVEL:
            match rating.strip().casefold():
                case "rated a":
                    return Rating.Everyone.value
                case (  # noqa: E211
                    "rated t+"
                    | "rated t"
                    | "marvel pg"
                    | "pg"
                    | "psr"
                    | "t+"
                    | "rated t +"
                    | "t+ suggested for teens and up"
                    | "teen+"
                    | "rated t teen"
                    | "t"
                    | "marvel psr"
                    | "teen plus"
                    | "rated t+ teen plus"
                    | "a"
                    | "t+ teen"
                    | "t+ - teen plus"
                    | "rated t / teen"
                    | "rated t+ / teen plus"
                    | "t+  suggested for teens and up"
                    | "teen t+"
                    | "t+ - teen"
                ):
                    return Rating.Teen.value
                case "parental advisory" | "psr+" | "parental advisory!":
                    return Rating.Teen_Plus.value
                case (  # noqa: E211
                    "approved by the comics code authority"
                    | "approved by the comics code autority"
                    | "authorized a. c. m. p. conforms to the comics code"
                    | "approved by the cosmic code authority [approved by the comics code authority]"  # noqa: E501
                ):
                    return Rating.CCA.value
                case _:
                    LOGGER.error(f"Invalid Rating for Marvel: '{rating}'")
                    return self._choose_rating(rating)

        match rating.strip().lower():
            # Everyone
            case "rated e / everyone" | "all ages" | "rated e everyone" | "ages 8+":
                return Rating.Everyone.value
            # Teen
            case (  # noqa: E211
                "rated t teen"
                | "rated t"
                | "ages 13+"
                | "pg"
                | "psr"
                | "rated a"
                | "teen 13+"
                | "teen"
                | "teen readers"
                | "rated teen"
                | "13+"
                | "rated t for teen"
                | "t teen"
                | "rated t / teen"
                | "t / teen"
                | "rated t/teen"
            ):
                return Rating.Teen.value
            # Teen Plus
            case (  # noqa: E211
                "rated t+"
                | "rated t+ teen plus"
                | "parental advisory"
                | "rated teen+  violence and mature content"
                | "rated teen +"
                | "teen + violence and mature content"
                | "teen +"
                | "rated teen + violence and mature content"
                | "teen+"
                | "t+"
                | "teen+ readers"
                | "t+ teen plus"
                | "rated teen+"
                | "rated t+ / teen plus"
                | "t+ / teen plus"
                | "t+/ teen plus"
                | "rated t teen+"
                | "teen plus"
                | "teen plus / t+"
            ):
                return Rating.Teen_Plus.value
            # Mature
            case (  # noqa: E211
                "suggested for mature readers"
                | "rated m / mature"
                | "rated m/mature"
                | "rated m mature"
                | "m / mature"
                | "mature readers"
                | "ages 17+"
                | "for mature readers"
                | "rated mature"
                | "parental advisory explicit content"
                | "mature"
                | "mature readers only"
                | "strongly suggested for mature readers!"
                | "suggested for mature grown-ups!"
                | "suggested for mature adults!"
                | "suggested for very, very mature readers!"
                | "rate m / mature"
                | "rated m"
                | "rating: m / mature"
                | "rating: m/ mature"
                | "rated m | mature"
                | "rated mature (m)"
                | "m/mature"
                | "rated / m mature"
                | "m/ mature"
                | "rated m/ mature"
            ):
                return Rating.Mature.value
            case (
                "approved by the comics code authority"
                | "authorized a. c. m. p. conforms to the comics code"
            ):
                return Rating.CCA.value
            case _:
                LOGGER.error(f"Invalid rating: '{rating}'")
                return self._choose_rating(rating)

    def set_number(self, number: str) -> str:
        # GCD sometimes add things like '[Newstand]' to their number string.
        if number == "[nn]":
            return "1"
        num_split = number.split(" ")
        result = num_split[0].strip()
        return result.replace(",", "")

    def set_page(self, page: Decimal) -> int | None:
        if page:
            p_split = str(page).split(".")
            return int(p_split[0])
        else:
            return None

    def set_barcode(self, barcode: str) -> str | None:
        return None if len(barcode) > 20 else barcode or None

    def set_price(self, price: str) -> Decimal | None:
        # print(price)
        if not price:
            return None
        # Ugh, found price with crap in it.
        price = price.replace(" (direct)", "")
        price = price.strip("[")
        price = price.strip("]")
        p_split = re.split(r";|:", price)
        for i in p_split:
            if i.__contains__("USD"):
                # Needed for prices without a delimiter
                p = i.split("USD ")
                # Needed for prices with a comma instead of a period.
                i = p[0].replace(",", ".")
                # Remove ths USD text
                new_price = i.strip(" USD")
                try:
                    return Decimal(new_price)
                except InvalidOperation:
                    print(f"Error converting {new_price}. Exiting...")
                    return None

        return None
