"""The user-supplied Fairuz sample, normalized from millisecond word starts.

This is a rendering corpus, not a YAML importer. Each word ends at the next
start, and the final word at the explicit line end. Source words include a
trailing space except for the final word; repeated words must remain distinct.
"""

from dataclasses import dataclass

from kotonoha.lyrics.models import LyricLine, LyricWord


@dataclass(frozen=True)
class ArabicLineCase:
    """One original line and its millisecond timing from Ana Indi Haneen."""

    text: str
    end_ms: int
    starts_ms: tuple[int, ...]

    def line(self, index: int) -> LyricLine:
        """Normalize the sample's start-only words into complete canonical spans."""
        parts = self.text.split(" ")
        ends = (*self.starts_ms[1:], self.end_ms)
        words = tuple(
            LyricWord(start / 1000.0, end / 1000.0, part + (" " if i < len(parts) - 1 else ""))
            for i, (part, start, end) in enumerate(zip(parts, self.starts_ms, ends, strict=True))
        )
        return LyricLine(index, f"L{index}", self.starts_ms[0] / 1000.0, self.end_ms / 1000.0, self.text, "", words)


ANA_INDI_HANEEN = (
    ArabicLineCase("أنا عندي حنين ما بعرف لمين", 66149, (60530, 61140, 61580, 61860, 62330, 64610)),
    ArabicLineCase("ليليي بيخطفني من بين السهرانين", 73122, (66980, 68460, 70370, 71140, 71340)),
    ArabicLineCase("أنا عندي حنين ما بعرف لمين", 78683, (75760, 75870, 76700, 76820, 76970, 77600)),
    ArabicLineCase("ليليي بيخطفني من بين السهرانين", 88165, (82120, 82990, 85340, 85630, 85990)),
    ArabicLineCase("بيصير يمشيني لبعيد يوديني", 96381, (89470, 91090, 94010, 95830)),
    ArabicLineCase("تا أعرف لمين و ما بعرف لمين", 102604, (96820, 97460, 98510, 100260, 100500, 100750, 102100)),
    ArabicLineCase("عديت الأسامي و محيت الأسامي", 155314, (149360, 150800, 153070, 153270, 154320)),
    ArabicLineCase("و نامي يا عينيي إذا راح فيكي تنامي", 162246,
                   (156400, 156670, 157270, 157830, 160050, 160480, 161020, 161330)),
    ArabicLineCase("عديت الأسامي و محيت الأسامي", 170033, (164070, 164800, 168000, 168210, 169110)),
    ArabicLineCase("و نامي يا عينيي إذا راح فيكي تنامي", 177193,
                   (171430, 171560, 172250, 172480, 173130, 175780, 175980, 176500)),
    ArabicLineCase("و بعدو هالحنين من خلف الحنين", 185230, (179060, 179250, 180320, 182630, 183050, 184170)),
    ArabicLineCase("بالدمع يغرقني و بأسامي المنسيين", 192310, (186360, 187769, 189718, 189863, 190789)),
    ArabicLineCase("تا أعرف لمين و ما بعرف لمين", 198873, (192310, 192380, 193360, 194030, 195990, 196180, 197530)),
    ArabicLineCase("أنا عندي حنين ما بعرف لمين", 206902, (200790, 200950, 202000, 204170, 204940, 205740)),
    ArabicLineCase("ليليي بيخطفني من بين السهرانين", 214111, (208130, 209410, 211650, 212010, 212550)),
    ArabicLineCase("بيصير يمشيني لبعيد يوديني", 221433, (215620, 216520, 219070, 220900)),
    ArabicLineCase("تا أعرف لمين و ما بعرف لمين لمين", 229645,
                   (222770, 222960, 224180, 226270, 226410, 226910, 227560, 228950)),
    ArabicLineCase("أنا خوفي يا حبي لتكون بعدك حبي", 278754,
                   (272620, 273180, 273710, 274330, 276480, 277230, 278350)),
    ArabicLineCase("و متهيألي نسيتك و أنتا مخبى بقلبي بقلبي", 287415,
                   (279930, 279940, 281830, 283480, 284240, 284540, 284830, 286160)),
    ArabicLineCase("أنا خوفي يا حبي لتكون بعدك حبي", 292652,
                   (287540, 287630, 288230, 289060, 290500, 291300, 292100)),
    ArabicLineCase("و متهيألي نسيتك و أنتا مخبى بقلبي", 301464,
                   (294740, 295020, 296900, 298200, 298420, 299370, 300880)),
    ArabicLineCase("و بتودي الحنين ليليي الحنين", 307785, (302190, 302410, 303530, 305080, 306660)),
    ArabicLineCase("يشلحني بالمنفى بعيونك الحلوين", 315148, (309290, 310530, 312440, 313980)),
    ArabicLineCase("تا أعرف لمين و ما بعرف لمين", 322598, (316590, 316950, 317300, 319990, 320130, 320250, 321720)),
    ArabicLineCase("أنا عندي حنين ما بعرف لمين", 329442, (323760, 324170, 324990, 327070, 327250, 328840)),
    ArabicLineCase("ليليي بيخطفني من بين السهرانين", 336831, (331260, 332190, 334690, 335080, 335440)),
    ArabicLineCase("بيصير يمشيني لبعيد يوديني", 344059, (338430, 339450, 342050, 343580)),
    ArabicLineCase("تا أعرف لمين و ما بعرف لمين", 351240, (345140, 345615, 346111, 348518, 348835, 349360, 350519)),
)
