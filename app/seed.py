"""Seed demo users and ~15 realistic reports (with generated placeholder photos).

    python -m app.seed            # idempotent: does nothing if items already exist
    python -m app.seed --force    # add the demo data even if the DB already has items

Demo login for every seeded account: password `demo12345`
(demo@findit.demo is the account to use in the live demo; the others own the sample reports).
"""

import io
import sys
from datetime import date, timedelta

from PIL import Image, ImageDraw
from sqlalchemy import func, select

from .database import SessionLocal, init_db
from .models import Item, User
from .security import hash_password
from .services.matching import find_matches, upsert_embedding
from .services.storage import process_image, save_image

PASSWORD = "demo12345"
USERS = [
    ("Demo User", "demo@findit.demo"),
    ("Asha Verma", "asha@findit.demo"),
    ("Ravi Kumar", "ravi@findit.demo"),
    ("Meera Nair", "meera@findit.demo"),
]

BG = (226, 230, 235)
COLORS = {
    "black": (28, 28, 32),
    "blue": (40, 80, 170),
    "brown": (120, 72, 40),
    "teal": (20, 150, 140),
    "red": (190, 40, 50),
    "maroon": (128, 24, 48),
    "green": (40, 140, 80),
    "silver": (170, 175, 182),
    "white": (245, 245, 245),
}


def _tone(c, delta):
    return tuple(max(0, min(255, v + delta)) for v in c)


# --- tiny placeholder illustrations; the object fills the centre of a 640x640 canvas ---
def _backpack(d, c):
    d.arc((250, 70, 390, 200), 180, 360, fill=_tone(c, 40), width=18)
    d.rounded_rectangle((190, 140, 450, 540), radius=70, fill=c)
    d.rounded_rectangle((230, 340, 410, 490), radius=28, fill=_tone(c, 30))
    d.line((320, 170, 320, 330), fill=_tone(c, 60), width=6)


def _phone(d, c):
    d.rounded_rectangle((220, 90, 420, 550), radius=36, fill=c)
    d.rounded_rectangle((236, 130, 404, 510), radius=14, fill=_tone(c, 55))


def _wallet(d, c):
    d.rounded_rectangle((130, 200, 510, 440), radius=30, fill=c)
    d.rounded_rectangle((130, 200, 510, 300), radius=30, fill=_tone(c, 25))
    d.ellipse((440, 290, 480, 330), fill=_tone(c, 70))


def _keys(d, c):
    d.ellipse((190, 150, 330, 290), outline=c, width=18)
    for x in (300, 340, 380):
        d.rectangle((x, 330, x + 34, 520), fill=c)
    d.rectangle((200, 280, 320, 330), fill=c)


def _bottle(d, c):
    d.rounded_rectangle((270, 70, 370, 130), radius=14, fill=_tone(c, -30))
    d.rounded_rectangle((240, 120, 400, 560), radius=50, fill=c)


def _idcard(d, c):
    d.rounded_rectangle((110, 190, 530, 450), radius=22, fill=c)
    d.rectangle((140, 230, 240, 360), fill=_tone(BG, -40))
    for y in (240, 290, 340):
        d.rectangle((270, y, 490, y + 22), fill=_tone(c, -60))


def _umbrella(d, c):
    d.pieslice((110, 90, 530, 400), 180, 360, fill=c)
    d.rectangle((310, 245, 330, 520), fill=_tone(c, 60))
    d.arc((290, 480, 350, 560), 0, 180, fill=_tone(c, 60), width=14)


def _notebook(d, c):
    d.rounded_rectangle((170, 90, 470, 550), radius=14, fill=c)
    d.rectangle((170, 90, 215, 550), fill=_tone(c, -35))
    d.rectangle((260, 180, 430, 250), fill=_tone(c, 60))


def _glasses(d, c):
    d.ellipse((120, 230, 290, 400), outline=c, width=16)
    d.ellipse((350, 230, 520, 400), outline=c, width=16)
    d.line((290, 300, 350, 300), fill=c, width=14)
    d.line((120, 280, 70, 250), fill=c, width=12)
    d.line((520, 280, 570, 250), fill=c, width=12)


def _handbag(d, c):
    d.arc((210, 90, 430, 300), 180, 360, fill=_tone(c, 50), width=16)
    d.polygon([(150, 540), (490, 540), (540, 240), (100, 240)], fill=c)
    d.rectangle((290, 290, 350, 340), fill=_tone(c, 70))


SHAPES = {
    "backpack": _backpack, "phone": _phone, "wallet": _wallet, "keys": _keys, "bottle": _bottle,
    "idcard": _idcard, "umbrella": _umbrella, "notebook": _notebook, "glasses": _glasses, "handbag": _handbag,
}


def make_image(shape: str, color: str) -> bytes:
    im = Image.new("RGB", (640, 640), BG)
    SHAPES[shape](ImageDraw.Draw(im), COLORS[color])
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


# owner index refers to USERS; days_ago is relative to today
ITEMS = [
    # ---- found reports (owned by the finders) ----
    dict(owner=1, type="found", title="Black backpack", category="bags", shape="backpack", color="black", days_ago=1,
         description="Black backpack with two zip compartments and padded straps, found on a bench outside the library.",
         location="Central Library, Main Block", features="Red keychain on the front zipper, small tear on the left strap",
         private="Contains a blue physics notebook and a steel water bottle"),
    dict(owner=1, type="found", title="Blue school backpack", category="bags", shape="backpack", color="blue", days_ago=2,
         description="Navy blue school bag with white stripes and a front pocket, left near the canteen tables.",
         location="Canteen", features="Name tag removed", private="Has a geometry box inside"),
    dict(owner=1, type="found", title="Black smartphone", category="electronics", shape="phone", color="black", days_ago=2,
         description="Black smartphone with a cracked screen protector and a floral back case, found in the seminar hall.",
         location="Seminar Hall B", features="Floral phone case, lock screen shows a mountain photo", private="Wallpaper is a photo of a golden retriever"),
    dict(owner=3, type="found", title="Brown leather wallet", category="wallets", shape="wallet", color="brown", days_ago=3,
         description="Brown bifold leather wallet, slightly worn at the corners, found at the bus stop.",
         location="Bus Stop near Main Gate", features="Initials stitched inside", private="Contains a library card"),
    dict(owner=1, type="found", title="Set of keys", category="keys", shape="keys", color="silver", days_ago=1,
         description="Three keys on a steel ring with a small blue tag, found in the parking lot.",
         location="Parking Lot A", features="Blue plastic tag, one key has a rubber cover", private="Tag has a number written on the back"),
    dict(owner=3, type="found", title="Teal steel water bottle", category="bottles", shape="bottle", color="teal", days_ago=4,
         description="Teal insulated steel water bottle with a dented base, left on the bleachers.",
         location="Sports Ground", features="Sticker of a mountain on the side", private="Name scratched under the base"),
    dict(owner=1, type="found", title="Student ID card", category="id_cards", shape="idcard", color="white", days_ago=2,
         description="College student ID card in a clear plastic holder, found near the admin office.",
         location="Admin Block", features="Blue lanyard attached", private="Roll number printed on the card"),
    dict(owner=3, type="found", title="Black umbrella", category="umbrellas", shape="umbrella", color="black", days_ago=3,
         description="Large black umbrella with a wooden handle, left in the main gate security room.",
         location="Main Gate", features="Wooden curved handle with a brass ring", private=None),
    dict(owner=1, type="found", title="Round spectacles", category="eyewear", shape="glasses", color="black", days_ago=1,
         description="Black round-framed spectacles with a thin metal bridge, found on a canteen table.",
         location="Canteen Seating Area", features="Small scratch on the left lens", private="Case had a prescription slip"),
    dict(owner=3, type="found", title="Maroon handbag", category="bags", shape="handbag", color="maroon", days_ago=2,
         description="Maroon faux-leather handbag with a gold clasp and a short handle, found in the auditorium.",
         location="Auditorium", features="Gold clasp, inner zip pocket", private=None),
    dict(owner=1, type="found", title="Green notebook", category="stationery", shape="notebook", color="green", days_ago=2,
         description="Green hardcover notebook with handwritten chemistry notes, found in the reading room.",
         location="Library Reading Room", features="Doodle of a flask on the first page", private="Name written on the last page"),
    # ---- lost reports (owned by people looking for their items) ----
    dict(owner=2, type="lost", title="Black smartphone", category="electronics", shape="phone", color="black", days_ago=3,
         description="Lost my black smartphone with a floral back case and a cracked screen protector near the seminar halls.",
         location="Seminar Hall A", features="Floral case", private=None),
    dict(owner=2, type="lost", title="Black-framed spectacles", category="eyewear", shape="glasses", color="black", days_ago=2,
         description="Round black-framed spectacles, lost somewhere around the canteen during lunch.",
         location="Canteen", features="Thin metal bridge", private=None),
    dict(owner=2, type="lost", title="Red handbag", category="bags", shape="handbag", color="red", days_ago=3,
         description="Red handbag with a gold clasp, lost after the cultural event in the auditorium.",
         location="Auditorium", features="Gold clasp", private=None),
    dict(owner=2, type="lost", title="Green chemistry notebook", category="stationery", shape="notebook", color="green", days_ago=3,
         description="Green hardcover notebook with chemistry notes, lost in the library reading room.",
         location="Library Reading Room", features="Flask doodle on the first page", private=None),
]


def main(force: bool = False) -> None:
    init_db()
    with SessionLocal() as db:
        if not force and (db.scalar(select(func.count()).select_from(Item)) or 0) > 0:
            print("Database already has items - skipping seed (use --force to add demo data anyway).")
            return

        users: list[User] = []
        for name, email in USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(name=name, email=email, password_hash=hash_password(PASSWORD))
                db.add(user)
                db.commit()
            users.append(user)

        today = date.today()
        created: list[Item] = []
        for spec in ITEMS:
            photo = process_image(make_image(spec["shape"], spec["color"]))
            item = Item(
                user_id=users[spec["owner"]].id,
                type=spec["type"],
                title=spec["title"],
                description=spec["description"],
                category=spec["category"],
                image_url=save_image(photo),
                location_text=spec["location"],
                date_event=today - timedelta(days=spec["days_ago"]),
                distinguishing_features=spec["features"],
                private_detail=spec["private"],
            )
            db.add(item)
            db.commit()
            upsert_embedding(db, item, photo)
            created.append(item)

        total = sum(len(find_matches(db, item)) for item in created if item.type == "lost")
        print(f"Seeded {len(users)} users and {len(created)} reports ({total} suggested matches).")
        print(f"Demo login: demo@findit.demo / {PASSWORD}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
