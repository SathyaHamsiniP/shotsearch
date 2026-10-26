"""Create reproducible synthetic printed-text fixtures, not a real-world benchmark."""
import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
CASES = {
 'traffic': 'MapMyIndia provides mapping technology and localized traffic intelligence.\nRoad navigation, logistics and urban planning.',
 'python_sum': 'def total(items):\n    return sum(items)\n\nprint(total([1, 2, 3]))',
 'python_loop': 'import math\n\ndef area(radius):\n    return math.pi * radius ** 2\n\nprint(area(5))',
 'java': 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello");\n    }\n}',
 'course': 'Course registration\nPython programming for beginners\nName: __________\nEmail: __________\nSubmit registration',
 'module_error': 'Traceback (most recent call last):\n  File "analysis.py", line 1, in <module>\n    import pandas\nModuleNotFoundError: No module named pandas',
 'syntax_error': 'File "main.py", line 8\n    if count > 0\n                ^\nSyntaxError: expected colon',
 'database_error': 'Database connection failed\nConnection refused on localhost:5432\nCheck that PostgreSQL is running.',
 'permission_error': 'PermissionError: Permission denied\nCannot write to protected directory\nChoose a writable output folder.',
 'git_error': 'fatal: not a git repository\nUse git init to create a repository.',
 'memory_error': 'MemoryError\nUnable to allocate array\nReduce batch size and try again.',
 'menu': 'Garden Cafe Menu\nMargherita pizza\nTomato pasta\nFresh salad\nOpening hours: 10 AM to 9 PM',
 'receipt': 'Grocery receipt\nMilk 60\nBread 45\nApples 120\nTotal 225',
 'meeting': 'Project meeting\nTuesday at 3 PM\nDiscuss website design\nBring your progress report.',
 'train': 'Train reservation\nBengaluru to Chennai\nDeparture: 07:30\nSeat: C2 42',
 'recipe': 'Tomato soup recipe\nCook tomatoes with garlic.\nBlend until smooth.\nSeason with salt and pepper.',
 'math': 'Linear algebra notes\nEigenvalues satisfy Av = lambda v.\nAn identity matrix has ones on its diagonal.',
 'crypto': 'Cryptocurrency market overview\nBitcoin prices changed today.\nTrading involves risk.',
 'logic': 'Boolean logic\nAND requires both inputs to be true.\nOR requires at least one true input.',
 'css': 'body {\n    background: white;\n    color: green;\n    font-size: 16px;\n}',
 'javascript': 'const numbers = [1, 2, 3];\nconst doubled = numbers.map(x => x * 2);\nconsole.log(doubled);',
 'notice': 'Library notice\nPlease return borrowed books by Friday.\nRenewals are available at the front desk.',
 'exercise': 'Weekly exercise plan\nMonday: walking\nWednesday: cycling\nFriday: swimming',
 'weather': 'Weather forecast\nHeavy rain expected tomorrow.\nCarry an umbrella.',
 'empty': '',
 'phrase_distractor': 'The connection to the database succeeded.\nAll services are healthy.'
}
QUERIES = [
 ('traffic','hybrid','traffic.png','development'),
 ('congestion','hybrid','traffic.png','development'),
 ('Python code','hybrid','python_sum.png;python_loop.png','development'),
 ('Java code','hybrid','java.png','development'),
 ('"course registration"','keyword','course.png','development'),
 ('ModuleNotFoundError','keyword','module_error.png','development'),
 ('missing package problem','hybrid','module_error.png','development'),
 ('"database connection"','keyword','database_error.png','development'),
 ('restaurant food options','hybrid','menu.png','development'),
 ('flight ticket','hybrid','','development'),
 ('PermissionError','keyword','permission_error.png','holdout'),
 ('books due date','hybrid','notice.png','holdout'),
 ('Boolean logic','keyword','logic.png','holdout'),
 ('dentist appointment','hybrid','','holdout')
]

def main():
    images = ROOT/'images'; images.mkdir(exist_ok=True)
    try: font = ImageFont.truetype('DejaVuSansMono.ttf', 25)
    except OSError: font = ImageFont.load_default(size=25)
    for i, (name, content) in enumerate(CASES.items()):
        dark = i % 3 == 0
        image = Image.new('RGB', (1100, 600), '#20252b' if dark else '#fafafa')
        ImageDraw.Draw(image).multiline_text((35, 45), content, font=font, fill='#f5f5f5' if dark else '#20252b', spacing=12)
        image.save(images/(name+'.png'))
    with (ROOT/'queries.csv').open('w', newline='', encoding='utf-8') as file:
        writer=csv.writer(file); writer.writerow(['query','mode','expected_files','split']); writer.writerows(QUERIES)
    print(f'Created {len(CASES)} synthetic images and {len(QUERIES)} labelled queries.')
if __name__ == '__main__': main()
