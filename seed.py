import json
import os


PRODUCTS = [
    {
        "name": "Blue Ballpoint Pen",
        "category": "Writing Instruments",
        "description": "Smooth blue ballpoint pen for class notes, filling forms, and quick everyday writing.",
        "price": 25,
        "original_price": 40,
        "stock": 120,
        "rating": 4.4,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "Gel Pen Pack",
        "category": "Writing Instruments",
        "description": "Comfort-grip gel pen set with smooth ink flow ideal for neat assignments and revision sheets.",
        "price": 90,
        "original_price": 130,
        "stock": 95,
        "rating": 4.5,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "HB Pencil Box",
        "category": "Writing Instruments",
        "description": "Pack of 10 standard HB pencils designed for exams, rough work, and clean sketches.",
        "price": 55,
        "original_price": 75,
        "stock": 150,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Mechanical Pencil Set",
        "category": "Writing Instruments",
        "description": "Refillable mechanical pencils with lead advancement for precise drawing and note-taking.",
        "price": 140,
        "original_price": 190,
        "stock": 84,
        "rating": 4.6,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "Soft Eraser Pack",
        "category": "Stationery Essentials",
        "description": "Non-dust erasers for clean corrections on paper, answer sheets, and drawing work.",
        "price": 30,
        "original_price": 45,
        "stock": 110,
        "rating": 4.2,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Pencil Sharpener",
        "category": "Stationery Essentials",
        "description": "Compact metal and plastic sharpener for regular classroom use and neat pencil tips.",
        "price": 35,
        "original_price": 55,
        "stock": 130,
        "rating": 4.1,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Highlighter Set",
        "category": "School Supplies",
        "description": "Set of neon highlighters for marking key notes, formulas, and chapter summaries.",
        "price": 85,
        "original_price": 120,
        "stock": 88,
        "rating": 4.4,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Permanent Marker Pack",
        "category": "School Supplies",
        "description": "Bold permanent markers for labeling, project sheets, and clear classroom signage.",
        "price": 110,
        "original_price": 155,
        "stock": 72,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Whiteboard Marker Set",
        "category": "School Supplies",
        "description": "Low-odour whiteboard markers in assorted colours for seminars and classroom discussions.",
        "price": 180,
        "original_price": 240,
        "stock": 63,
        "rating": 4.5,
        "featured": 1,
        "is_essential": 0,
    },
    {
        "name": "30 cm Plastic Ruler",
        "category": "Math & Geometry Supplies",
        "description": "Transparent measuring ruler with edge markings for technical drawing and precise layouts.",
        "price": 40,
        "original_price": 65,
        "stock": 200,
        "rating": 4.2,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Geometry Box Set",
        "category": "Math & Geometry Supplies",
        "description": "Complete geometry box with compass, protractor, scale, and divider for engineering drawing work.",
        "price": 230,
        "original_price": 320,
        "stock": 68,
        "rating": 4.7,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "A4 Ruled Notebook",
        "category": "Paper & Notebooks",
        "description": "A4 ruled notebook with high-quality pages for classroom notes, assignment work, and revision.",
        "price": 120,
        "original_price": 170,
        "stock": 120,
        "rating": 4.6,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "Long Notebook 200 Pages",
        "category": "Paper & Notebooks",
        "description": "Long-format notebook with 200 pages designed for semester-long lecture notes and lab records.",
        "price": 150,
        "original_price": 200,
        "stock": 94,
        "rating": 4.5,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Spiral Notebook",
        "category": "Paper & Notebooks",
        "description": "Strong spiral notebook with durable sheets for everyday classwork and quick study notes.",
        "price": 95,
        "original_price": 135,
        "stock": 142,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Sticky Notes Pack",
        "category": "Office Supplies",
        "description": "Colourful sticky notes for reminders, task labels, and quick revision markers.",
        "price": 70,
        "original_price": 95,
        "stock": 160,
        "rating": 4.1,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Index Card Set",
        "category": "Office Supplies",
        "description": "Pack of indexed cards for flashcards, revision prompts, and quick study aids.",
        "price": 65,
        "original_price": 90,
        "stock": 110,
        "rating": 4.2,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "File Folder Pack",
        "category": "Office Supplies",
        "description": "Durable file folders for assignments, certificates, and organized academic records.",
        "price": 140,
        "original_price": 190,
        "stock": 86,
        "rating": 4.4,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "Document File Set",
        "category": "Office Supplies",
        "description": "Set of document sleeves and disposable files for organizing exam sheets and forms.",
        "price": 110,
        "original_price": 155,
        "stock": 98,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 1,
    },
    {
        "name": "Clip Board",
        "category": "Office Supplies",
        "description": "Portable clipboard for writing on the go, fieldwork, or exam hall note review.",
        "price": 190,
        "original_price": 260,
        "stock": 76,
        "rating": 4.4,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Heavy Duty Stapler",
        "category": "Office Supplies",
        "description": "Reliable stapler for binding notes, reports, and assignment sheets with ease.",
        "price": 210,
        "original_price": 285,
        "stock": 52,
        "rating": 4.5,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Staples Box",
        "category": "Office Supplies",
        "description": "Pack of standard staples for all your daily office and assignment binding needs.",
        "price": 35,
        "original_price": 55,
        "stock": 180,
        "rating": 4.1,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Paper Clip Pack",
        "category": "Office Supplies",
        "description": "Assorted paper clips for organizing loose sheets, notes, and important documents.",
        "price": 45,
        "original_price": 70,
        "stock": 170,
        "rating": 4.0,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Binder Clip Set",
        "category": "Office Supplies",
        "description": "Multi-size binder clips for securing notes, lab sheets, and study material stacks.",
        "price": 65,
        "original_price": 90,
        "stock": 150,
        "rating": 4.2,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Glue Stick Pack",
        "category": "Craft & Project Supplies",
        "description": "Strong glue sticks for model-making, mini projects, and paper craft assignments.",
        "price": 75,
        "original_price": 100,
        "stock": 92,
        "rating": 4.4,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Adhesive Tape Roll",
        "category": "Craft & Project Supplies",
        "description": "Transparent adhesive tape for neat mounting, repair work, and classroom craft tasks.",
        "price": 50,
        "original_price": 75,
        "stock": 170,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "Student Scissors",
        "category": "Craft & Project Supplies",
        "description": "Sharp student scissors with ergonomic handles for paper cutting and project work.",
        "price": 120,
        "original_price": 165,
        "stock": 76,
        "rating": 4.5,
        "featured": 0,
        "is_essential": 0,
    },
    {
        "name": "A4 Paper Pack",
        "category": "Paper & Notebooks",
        "description": "Pack of premium A4 sheets for assignments, printouts, and project reports.",
        "price": 180,
        "original_price": 245,
        "stock": 90,
        "rating": 4.6,
        "featured": 1,
        "is_essential": 1,
    },
    {
        "name": "Drawing Book",
        "category": "Art & Design",
        "description": "Sketch-friendly drawing book with thick pages for art classes, creativity, and plans.",
        "price": 135,
        "original_price": 185,
        "stock": 74,
        "rating": 4.7,
        "featured": 1,
        "is_essential": 0,
    },
    {
        "name": "Sketch Pen Set",
        "category": "Art & Design",
        "description": "Vibrant sketch pens for diagrams, illustrations, and presentation boards.",
        "price": 165,
        "original_price": 220,
        "stock": 58,
        "rating": 4.6,
        "featured": 1,
        "is_essential": 0,
    },
    {
        "name": "Pencil Pouch",
        "category": "Storage & Organization",
        "description": "Spacious pencil pouch to keep pens, pencils, erasers, and mini tools organized.",
        "price": 110,
        "original_price": 150,
        "stock": 83,
        "rating": 4.3,
        "featured": 0,
        "is_essential": 1,
    },
]

EXTRA_PRODUCTS = [
    ("Black Ballpoint Pen", "Writing Instruments", "Black ballpoint pens for lectures, forms, and everyday campus writing.", 25, 40, 100, 4.3, 0, 1),
    ("Fountain Pen", "Writing Instruments", "Refillable fountain pen for smooth handwriting, journaling, and thoughtful note-taking.", 240, 320, 38, 4.5, 0, 0),
    ("Graph Notebook", "Paper & Notebooks", "Grid-ruled notebook for mathematics, charts, engineering sketches, and data work.", 105, 145, 75, 4.4, 0, 1),
    ("Record Notebook", "Paper & Notebooks", "Ruled record notebook for maintaining coursework, assignments, and academic records.", 145, 190, 60, 4.4, 0, 1),
    ("Practical Observation Notebook", "Paper & Notebooks", "Observation notebook for recording practical exercises, results, and lab notes.", 125, 165, 54, 4.3, 0, 1),
    ("Ruled Notebook Pack", "Paper & Notebooks", "Pack of ruled notebooks for lectures, revision, and semester study notes.", 220, 290, 65, 4.5, 1, 1),
    ("Drawing Sheets Pack", "Paper & Notebooks", "Smooth drawing sheets for technical diagrams, classroom art, and project work.", 95, 130, 80, 4.4, 0, 0),
    ("Mathematical Instrument Set", "Math & Geometry Supplies", "Drawing instruments for geometry, technical drawing, and classroom exercises.", 260, 340, 45, 4.6, 1, 1),
    ("Document Organizer", "Office Supplies", "Portable organizer for assignments, certificates, printouts, and study documents.", 180, 240, 42, 4.4, 0, 1),
    ("Desk File Folder", "Office Supplies", "Desktop file folder for keeping coursework and important papers neatly arranged.", 160, 210, 48, 4.3, 0, 1),
    ("Coloured Pencil Set", "Art & Design", "Coloured pencils for diagrams, illustrations, sketching, and creative coursework.", 175, 230, 55, 4.6, 0, 0),
    ("Wax Crayon Set", "Art & Design", "Bright wax crayons for art projects, poster work, and colourful study diagrams.", 90, 125, 63, 4.3, 0, 0),
    ("Watercolour Set", "Art & Design", "Watercolour set for painting, design assignments, and creative study projects.", 210, 280, 37, 4.5, 1, 0),
    ("Paintbrush Set", "Art & Design", "Assorted paintbrushes for watercolour practice, craft work, and project boards.", 135, 180, 40, 4.4, 0, 0),
    ("Chart Paper Pack", "Craft & Project Supplies", "Coloured chart sheets for classroom presentations, diagrams, and group projects.", 120, 160, 72, 4.5, 1, 0),
    ("Craft Paper Pack", "Craft & Project Supplies", "Assorted craft paper for displays, model making, and creative assignments.", 110, 150, 69, 4.4, 0, 0),
    ("Project Board", "Craft & Project Supplies", "Sturdy presentation board for academic displays, diagrams, and student projects.", 95, 130, 58, 4.5, 1, 0),
    ("Bedsheet - Single", "Hostel and Daily Essentials", "Single-bed cotton-style bedsheet sample listing for a student hostel room.", 450, 590, 28, 4.4, 1, 1),
    ("Pillow Cover Pair", "Hostel and Daily Essentials", "Pair of pillow covers for hostel bedding and easy weekly laundry rotation.", 180, 240, 35, 4.3, 0, 1),
    ("Standard Bed Pillow", "Hostel and Daily Essentials", "Standard bed pillow for a dorm or hostel sleeping setup.", 350, 460, 24, 4.4, 0, 1),
    ("Lightweight Blanket", "Hostel and Daily Essentials", "Lightweight blanket sample listing for hostel rooms and cool evenings.", 650, 850, 19, 4.5, 0, 1),
    ("Lightweight Comforter", "Hostel and Daily Essentials", "Comforter sample listing for student accommodation and single beds.", 950, 1250, 16, 4.5, 0, 1),
    ("Mattress Protector", "Hostel and Daily Essentials", "Protective mattress cover sample listing for keeping hostel bedding tidy.", 520, 690, 18, 4.3, 0, 1),
    ("Laundry Bag", "Hostel and Daily Essentials", "Reusable laundry bag for separating clothes in shared hostel facilities.", 160, 220, 43, 4.4, 0, 1),
    ("Storage Box", "Hostel and Daily Essentials", "Compact storage box for keeping dorm-room supplies and personal items organized.", 290, 390, 33, 4.5, 0, 1),
    ("Drawer Organizer Set", "Hostel and Daily Essentials", "Organizer trays for arranging stationery, toiletries, and small hostel essentials.", 240, 320, 28, 4.4, 0, 1),
    ("Clothes Hangers Pack", "Hostel and Daily Essentials", "Pack of clothes hangers to organize a student wardrobe in limited space.", 180, 240, 46, 4.3, 0, 1),
    ("Over-door Shoe Organizer", "Hostel and Daily Essentials", "Space-saving hanging organizer sample listing for a shared student room.", 390, 520, 21, 4.2, 0, 1),
    ("Desk Organizer", "Hostel and Daily Essentials", "Desktop organizer for study materials, small accessories, and everyday essentials.", 260, 350, 30, 4.5, 1, 1),
    ("Washi-Style Decorative Tape", "Craft & Project Supplies", "Japanese washi-style decorative paper tape for journaling, planners, and creative study notes. Sample listing; manufacturing origin is not verified.", 120, 160, 34, 4.5, 1, 0),
    ("Clean Code", "Books", "Programming book sample listing about readable software design and maintainable code. Price is a demonstration price.", 520, 699, 18, 4.8, 1, 0),
    ("Python Crash Course", "Books", "Beginner-friendly Python programming book sample listing with hands-on coding projects.", 680, 899, 16, 4.8, 1, 0),
    ("Introduction to Algorithms", "Books", "Computer science reference text sample listing covering core algorithms and analysis.", 1120, 1499, 12, 4.7, 1, 0),
    ("The Pragmatic Programmer", "Books", "Software development reference book sample listing for programming students.", 720, 950, 14, 4.8, 1, 0),
    ("Data Structures and Algorithms in Python", "Books", "Programming reference text sample listing for data structures and algorithm study.", 840, 1099, 13, 4.6, 0, 0),
    ("Hostel Soap Bar", "Hostel and Daily Essentials", "Single bar soap sample listing for a student's hostel toiletry kit.", 35, 50, 55, 4.2, 1, 1),
    ("Dove Shampoo Bottle", "Hostel and Daily Essentials", "Dove shampoo sample listing for hostel personal care. Demonstration price, not a live offer.", 145, 180, 32, 4.4, 0, 1),
    ("Vitis Toothpaste Tube", "Hostel and Daily Essentials", "Vitis toothpaste sample listing for everyday hostel oral care.", 110, 140, 24, 4.3, 0, 1),
    ("Breda Toothbrush", "Hostel and Daily Essentials", "Breda toothbrush sample listing for a compact hostel wash kit.", 55, 75, 35, 4.2, 0, 1),
    ("Instant Noodles Pack", "Hostel and Daily Essentials", "Shrimp-flavoured instant noodles sample listing. Check the package and dietary information before purchase.", 40, 55, 48, 4.2, 1, 1),
    ("Packaged Biscuits", "Hostel and Daily Essentials", "Packaged biscuits sample listing for a quick hostel snack. Demonstration price.", 50, 70, 40, 4.3, 1, 1),
    ("Hershey's Chocolate Bar", "Hostel and Daily Essentials", "Hershey's chocolate bar sample listing for an occasional packaged snack.", 65, 85, 28, 4.4, 1, 1),
    ("Ruffles Potato Chips", "Hostel and Daily Essentials", "Ruffles potato chips sample listing. Check the package for allergens and dietary details.", 75, 95, 26, 4.3, 0, 1),
    ("Reusable Water Bottle Set", "Hostel and Daily Essentials", "Reusable student water bottle sample listing for lectures, study sessions, and hostel use.", 220, 290, 30, 4.5, 1, 1),
    ("Ceramic Hostel Mug", "Hostel and Daily Essentials", "Ceramic mug sample listing for tea, coffee, and everyday hostel use.", 150, 200, 24, 4.4, 0, 1),
]

# These remain illustrative prices, but separate unrelated products that would
# otherwise appear to share the same SKU price in this demo catalogue.
SAMPLE_PRICE_OVERRIDES = {
    "Black Ballpoint Pen": 26,
    "Pencil Sharpener": 36,
    "Staples Box": 37,
    "Instant Noodles Pack": 42,
    "Packaged Biscuits": 52,
    "HB Pencil Box": 57,
    "Hershey's Chocolate Bar": 67,
    "Index Card Set": 69,
    "Ruffles Potato Chips": 77,
    "Wax Crayon Set": 92,
    "Project Board": 97,
    "Spiral Notebook": 99,
    "Document File Set": 112,
    "Pencil Pouch": 114,
    "Permanent Marker Pack": 116,
    "Vitis Toothpaste Tube": 118,
    "Chart Paper Pack": 122,
    "Student Scissors": 124,
    "Washi-Style Decorative Tape": 126,
    "Paintbrush Set": 137,
    "Mechanical Pencil Set": 142,
    "Record Notebook": 147,
    "Long Notebook 200 Pages": 152,
    "Laundry Bag": 162,
    "Clothes Hangers Pack": 182,
    "Document Organizer": 184,
    "Pillow Cover Pair": 186,
    "Whiteboard Marker Set": 188,
    "Watercolour Set": 212,
    "Ruled Notebook Pack": 222,
    "Fountain Pen": 242,
    "Mathematical Instrument Set": 262,
    "Mattress Protector": 530,
}

INTERNATIONAL_STYLES = {
    "Gel Pen Pack": ("South Korea-inspired stationery", "South Korea-inspired; not a manufacturing-origin claim", "pastel korean korea gel pen writing"),
    "Highlighter Set": ("South Korea-inspired stationery", "South Korea-inspired; not a manufacturing-origin claim", "pastel korean korea highlighter study"),
    "Sticky Notes Pack": ("South Korea-inspired stationery", "South Korea-inspired; not a manufacturing-origin claim", "korean korea memo pad sticky notes journaling"),
    "Mechanical Pencil Set": ("Japan-inspired stationery", "Japan-inspired; not a manufacturing-origin claim", "japan japanese mechanical pencil study"),
    "Fountain Pen": ("Japan-inspired stationery", "Japan-inspired; not a manufacturing-origin claim", "japan japanese pen writing"),
    "Soft Eraser Pack": ("Japan-inspired stationery", "Japan-inspired; not a manufacturing-origin claim", "japan japanese compact eraser"),
    "A4 Ruled Notebook": ("USA college stationery style", "USA-inspired; not a manufacturing-origin claim", "usa college ruled notebook"),
    "Index Card Set": ("USA college stationery style", "USA-inspired; not a manufacturing-origin claim", "usa flashcards index cards study"),
    "Sketch Pen Set": ("International creative stationery", "Country of manufacture not verified", "international art sketch pens stationery"),
    "Drawing Book": ("International creative stationery", "Country of manufacture not verified", "international journaling sketch notebook"),
    "Washi-Style Decorative Tape": ("Japan-inspired stationery", "Japan-inspired; not a manufacturing-origin claim", "washi tape japanese japan decorative paper tape planner journaling"),
}

PRODUCT_IMAGE_OVERRIDES = {
    "A4 Paper Pack": {
        "image_url": "/static/images/paper-pack.svg",
        "image_alt": "Illustration of a ream of A4 paper; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Chart Paper Pack": {
        "image_url": "/static/images/chart-paper-pack.svg",
        "image_alt": "Illustration of coloured chart sheets; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Craft Paper Pack": {
        "image_url": "/static/images/craft-paper-pack.svg",
        "image_alt": "Illustration of assorted craft paper; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Document Organizer": {
        "image_url": "/static/images/document-organizer.svg",
        "image_alt": "Illustration of a multi-pocket document organizer; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Mathematical Instrument Set": {
        "image_url": "/static/images/mathematical-instrument-set.svg",
        "image_alt": "Illustration of geometry drawing instruments; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Pencil Sharpener": {
        "image_url": "/static/images/sharpener.svg",
        "image_alt": "Illustration of a compact pencil sharpener; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Project Board": {
        "image_url": "/static/images/project-board.svg",
        "image_alt": "Illustration of an academic presentation board; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Staples Box": {
        "image_url": "/static/images/staples.svg",
        "image_alt": "Illustration of a box of metal staples; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Desk Organizer": {
        "image_url": "/static/images/desk-organizer.svg",
        "image_alt": "Illustration of a desktop stationery organizer; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Over-door Shoe Organizer": {
        "image_url": "/static/images/overdoor-shoe-organizer.svg",
        "image_alt": "Illustration of an over-door pocket shoe organizer; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "Lightweight Blanket": {
        "image_url": "/static/images/lightweight-blanket.svg",
        "image_alt": "Illustration of a folded lightweight blanket; product photograph unavailable.",
        "image_credit_url": "",
        "image_credit_text": "",
    },
    "30 cm Plastic Ruler": {
        "image_url": "/static/images/catalog/plastic-ruler.jpg",
        "image_credit_url": "https://commons.wikimedia.org/wiki/File:Plastic_ruler.jpg",
        "image_credit_text": "Corn cheese · CC0",
    },
    "Bedsheet - Single": {
        "image_url": "/static/images/catalog/bedsheet-students.jpg",
        "image_credit_url": "https://commons.wikimedia.org/wiki/File:Azama_Bedsheet_Students.jpg",
        "image_credit_text": "Wikimedia Commons · creator and licence at source",
    },
    "Sticky Notes Pack": {
        "image_url": "/static/images/catalog/sticky-notes-wall.jpg",
        "image_credit_url": "https://commons.wikimedia.org/wiki/File:Dash_Coffee_at_Gate_1_Dasma_-_Interior_-_Post-it_notes_wall_1.jpg",
        "image_credit_text": "UndueMarmot · CC0",
    },
    "Washi-Style Decorative Tape": {
        "image_url": "/static/images/catalog/washi-tape.jpg",
        "image_credit_url": "https://commons.wikimedia.org/wiki/File:Washi_tape.jpg",
        "image_credit_text": "Mike Dickison · CC BY 4.0",
    },
}

PRODUCT_BRANDS = {
    "Dove Shampoo Bottle": "Dove",
    "Vitis Toothpaste Tube": "Vitis",
    "Breda Toothbrush": "Breda",
    "Hershey's Chocolate Bar": "Hershey's",
    "Ruffles Potato Chips": "Ruffles",
}

HOSTEL_PRODUCTS = {
    "Bedsheet - Single", "Pillow Cover Pair", "Standard Bed Pillow",
    "Lightweight Blanket", "Lightweight Comforter", "Mattress Protector",
    "Laundry Bag", "Storage Box", "Drawer Organizer Set",
    "Clothes Hangers Pack", "Over-door Shoe Organizer", "Desk Organizer",
    "Hostel Soap Bar", "Dove Shampoo Bottle", "Vitis Toothpaste Tube",
    "Breda Toothbrush", "Instant Noodles Pack", "Packaged Biscuits",
    "Hershey's Chocolate Bar", "Ruffles Potato Chips", "Reusable Water Bottle Set",
    "Ceramic Hostel Mug",
}

SNACK_PRODUCTS = {
    "Instant Noodles Pack", "Packaged Biscuits", "Hershey's Chocolate Bar",
    "Ruffles Potato Chips",
}

BOOK_COVERS = {
    "Clean Code": ("9780132350884", "clean-code-cover.jpg"),
    "Python Crash Course": ("9781718502703", "python-crash-course-cover.jpg"),
    "Introduction to Algorithms": ("9780262046305", "introduction-to-algorithms-cover.jpg"),
    "The Pragmatic Programmer": ("9780135957059", "pragmatic-programmer-cover.jpg"),
    "Data Structures and Algorithms in Python": ("9781118290279", "data-structures-python-cover.jpg"),
}

HOSTEL_PHOTOS = {
    "Hostel Soap Bar": (
        "/static/images/catalog/hostel-soap-bar.jpg",
        "https://commons.wikimedia.org/wiki/File:Cold_Cream_Soap_Hilko,_soap_bar,_pic2.JPG",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Dove Shampoo Bottle": (
        "/static/images/catalog/dove-shampoo-bottle.jpg",
        "https://commons.wikimedia.org/wiki/File:Dove_shampoo_bottle.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Vitis Toothpaste Tube": (
        "/static/images/catalog/vitis-toothpaste-tube.jpg",
        "https://commons.wikimedia.org/wiki/File:Vitis_Dentaid_toothpaste_tube,_Hillegersberg,_Rotterdam_(2021)_01.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Breda Toothbrush": (
        "/static/images/catalog/breda-toothbrush.jpg",
        "https://commons.wikimedia.org/wiki/File:Breda_toothbrush.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Instant Noodles Pack": (
        "/static/images/catalog/instant-noodles.jpg",
        "https://commons.wikimedia.org/wiki/File:Five_packs_of_shrimp-flavoured_instant_noodles.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Packaged Biscuits": (
        "/static/images/catalog/packaged-biscuits.jpg",
        "https://commons.wikimedia.org/wiki/File:Biscuits_Leclerc.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Hershey's Chocolate Bar": (
        "/static/images/catalog/hersheys-chocolate-bar.jpg",
        "https://commons.wikimedia.org/wiki/File:HERSHEY%27S_Chocolate_Bar_Greatest_Milk_Chocolate.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Ruffles Potato Chips": (
        "/static/images/catalog/ruffles-potato-chips.jpg",
        "https://commons.wikimedia.org/wiki/File:Opened_bag_of_Ruffles_All_Dressed_potato_chips.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Reusable Water Bottle Set": (
        "/static/images/catalog/reusable-water-bottles.jpg",
        "https://commons.wikimedia.org/wiki/File:Multiple_reusable_water_bottles.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
    "Ceramic Hostel Mug": (
        "/static/images/catalog/ceramic-hostel-mug.jpg",
        "https://commons.wikimedia.org/wiki/File:2004_MujiWanoSyokki-TeasetMug_Masahiro-Mori.jpg",
        "Wikimedia Commons · creator and licence at source",
    ),
}


def seed_products(connection):
    sources_path = os.path.join(os.path.dirname(__file__), "static", "images", "catalog_sources.json")
    with open(sources_path, "r", encoding="utf-8") as source_file:
        image_sources = json.load(source_file)

    existing_names = {
        row["name"] for row in connection.execute("SELECT name FROM products").fetchall()
    }
    product_data = list(PRODUCTS)
    product_data.extend(
        {
            "name": name,
            "category": category,
            "description": description,
            "price": price,
            "original_price": original_price,
            "stock": stock,
            "rating": rating,
            "featured": featured,
            "is_essential": essential,
        }
        for name, category, description, price, original_price, stock, rating, featured, essential in EXTRA_PRODUCTS
    )
    for item in product_data:
        sample_price = SAMPLE_PRICE_OVERRIDES.get(item["name"], item["price"])
        image_source = image_sources.get(item["name"], {})
        image_override = PRODUCT_IMAGE_OVERRIDES.get(item["name"], {})
        hostel_photo = HOSTEL_PHOTOS.get(item["name"])
        book_cover = BOOK_COVERS.get(item["name"])
        image_url = (hostel_photo[0] if hostel_photo else
            f"/static/images/catalog/{book_cover[1]}" if book_cover else
            image_override.get("image_url", image_source.get(
            "image_url",
            PRODUCT_IMAGES.get(item["name"], "/static/images/placeholder-product.svg"),
        )))
        style_label, country_label, tags = INTERNATIONAL_STYLES.get(item["name"], ("", "", ""))
        is_international = int(bool(style_label))
        is_hostel = int(item["name"] in HOSTEL_PRODUCTS)
        # Seeded prices and ratings are demonstrations, not verified discounts or reviews.
        original_price = None
        rating = None
        if is_hostel:
            category = "Hostel Essentials"
        elif item["category"] == "Books":
            category = "Books"
        else:
            category = "Stationery"
        brand = PRODUCT_BRANDS.get(item["name"], "")
        subcategory = "Food and Snacks" if item["name"] in SNACK_PRODUCTS else item["category"]
        intended_use = item["description"]
        search_terms = " ".join(
            value for value in (
                item["name"], category,
                item["description"], style_label, country_label, tags, brand,
            ) if value
        )
        image_alt = image_override.get("image_alt", item["name"])
        if book_cover:
            image_credit_url = f"https://openlibrary.org/isbn/{book_cover[0]}"
            image_credit_text = "Open Library cover image"
        elif hostel_photo:
            image_credit_url, image_credit_text = hostel_photo[1], hostel_photo[2]
        else:
            image_credit_url = image_override.get("image_credit_url", image_source.get("image_credit_url", ""))
            image_credit_text = image_override.get("image_credit_text", image_source.get("image_credit_text", ""))
        if item["name"] in existing_names:
            connection.execute(
                """
                UPDATE products
                SET category = ?, description = ?, price = ?, original_price = ?,
                    image_url = ?, image_credit_url = ?, image_credit_text = ?, style_label = ?,
                    country_label = ?, search_tags = ?, brand = ?, subcategory = ?,
                    tags = ?, intended_use = ?, image_alt = ?, is_international = ?,
                    is_hostel = ?, rating = ?, featured = ?, is_essential = ?
                WHERE name = ?
                """,
                (
                    category,
                    item["description"],
                    sample_price,
                    original_price,
                    image_url,
                    image_credit_url,
                    image_credit_text,
                    style_label,
                    country_label,
                    tags,
                    brand,
                    subcategory,
                    search_terms,
                    intended_use,
                    image_alt,
                    is_international,
                    is_hostel,
                    rating,
                    item["featured"],
                    item["is_essential"],
                    item["name"],
                ),
            )
            if book_cover:
                connection.execute(
                    "UPDATE products SET specifications = ? WHERE name = ?",
                    (f"ISBN: {book_cover[0]}", item["name"]),
                )
            continue
        connection.execute(
            """
            INSERT INTO products (
                name, category, description, price, original_price, stock, image_url,
                image_credit_url, image_credit_text, style_label, country_label, search_tags,
                brand, subcategory, tags, intended_use, image_alt,
                specifications, is_international, is_hostel, rating, featured, is_essential
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["name"],
                category,
                item["description"],
                sample_price,
                original_price,
                item["stock"],
                image_url,
                image_credit_url,
                image_credit_text,
                style_label,
                country_label,
                tags,
                brand,
                subcategory,
                search_terms,
                intended_use,
                image_alt,
                f"ISBN: {book_cover[0]}" if book_cover else "",
                is_international,
                is_hostel,
                rating,
                item["featured"],
                item["is_essential"],
            ),
        )

    sample_offers = (
        {
            "product_name": "Gel Pen Pack",
            "title": "Student Cart demo offer: 10% off",
            "offer_type": "percentage",
            "value": 10,
            "min_quantity": 1,
            "starts_at": "2026-10-01 00:00:00",
            "ends_at": "2026-12-31 23:59:59",
            "terms": "Student Cart sample offer only; not supplied by the brand.",
        },
        {
            "product_name": "A4 Ruled Notebook",
            "title": "Student Cart demo offer: save ₹10 on 2 or more",
            "offer_type": "fixed",
            "value": 10,
            "min_quantity": 2,
            "starts_at": "2026-10-01 00:00:00",
            "ends_at": "2026-12-31 23:59:59",
            "terms": "₹10 off each notebook when buying at least 2; Student Cart demo, not supplied by a brand.",
        },
        {
            "product_name": "Instant Noodles Pack",
            "title": "Student Cart demo offer: 5% off 3 or more",
            "offer_type": "percentage",
            "value": 5,
            "min_quantity": 3,
            "starts_at": "2026-10-01 00:00:00",
            "ends_at": "2026-12-31 23:59:59",
            "terms": "5% off each pack when buying at least 3; Student Cart demo, not supplied by a brand.",
        },
    )
    for offer in sample_offers:
        product = connection.execute(
            "SELECT id FROM products WHERE name = ?",
            (offer["product_name"],),
        ).fetchone()
        if product is None:
            continue
        connection.execute(
            """
            INSERT OR IGNORE INTO product_offers (
                product_id, title, offer_type, value, min_quantity,
                starts_at, ends_at, terms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"],
                offer["title"],
                offer["offer_type"],
                offer["value"],
                offer["min_quantity"],
                offer["starts_at"],
                offer["ends_at"],
                offer["terms"],
            ),
        )


PRODUCT_IMAGES = {
    "Blue Ballpoint Pen": "/static/images/ballpoint-pen.svg",
    "Gel Pen Pack": "/static/images/gel-pen.svg",
    "HB Pencil Box": "/static/images/pencil.svg",
    "Mechanical Pencil Set": "/static/images/mechanical-pencil.svg",
    "Soft Eraser Pack": "/static/images/eraser.svg",
    "Pencil Sharpener": "/static/images/sharpener.svg",
    "Highlighter Set": "/static/images/highlighter.svg",
    "Permanent Marker Pack": "/static/images/permanent-marker.svg",
    "Whiteboard Marker Set": "/static/images/whiteboard-marker.svg",
    "30 cm Plastic Ruler": "/static/images/ruler.svg",
    "Geometry Box Set": "/static/images/geometry-box.svg",
    "A4 Ruled Notebook": "/static/images/notebook.svg",
    "Long Notebook 200 Pages": "/static/images/long-notebook.svg",
    "Spiral Notebook": "/static/images/spiral-notebook.svg",
    "Sticky Notes Pack": "/static/images/sticky-notes.svg",
    "Index Card Set": "/static/images/index-cards.svg",
    "File Folder Pack": "/static/images/file-folder.svg",
    "Document File Set": "/static/images/document-file.svg",
    "Clip Board": "/static/images/clipboard.svg",
    "Heavy Duty Stapler": "/static/images/stapler.svg",
    "Staples Box": "/static/images/staples.svg",
    "Paper Clip Pack": "/static/images/paper-clips.svg",
    "Binder Clip Set": "/static/images/binder-clips.svg",
    "Glue Stick Pack": "/static/images/glue-stick.svg",
    "Adhesive Tape Roll": "/static/images/adhesive-tape.svg",
    "Student Scissors": "/static/images/scissors.svg",
    "A4 Paper Pack": "/static/images/paper-pack.svg",
    "Drawing Book": "/static/images/drawing-book.svg",
    "Sketch Pen Set": "/static/images/sketch-pens.svg",
    "Pencil Pouch": "/static/images/pencil-pouch.svg",
}
