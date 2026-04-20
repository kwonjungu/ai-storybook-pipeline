#!/usr/bin/env python3
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ORDER = ['bsl02_id','bsl03_id','bsl04_id','bsl05_id','bsl07_id','saram18_id','id01','space01_id']

YT_TITLE_FIX = {
    'bsl02_id': 'Petualangan Biji Soli dan Tupai | Dongeng Anak Indonesia | Belajar Sains Alam',
}
CHAR_FIX = {
    'bsl02_id':   ['Soli', 'Tupai'],
    'bsl05_id':   ['Duri', 'Turi'],
    'saram18_id': ['Ami', 'Bubi'],
    'space01_id': ['Mongsili', 'Koko'],
}

DESCS = {
'bsl02_id': (
    "Musim semi penuh kejutan! Soli dan Tupai menemukan biji kecil yang menyimpan petualangan luar biasa.\n"
    "Bersama-sama, mereka belajar bahwa setiap biji punya cerita — dan dengan perawatan serta kerja keras, sesuatu yang kecil bisa tumbuh menjadi besar!\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Cara merawat tanaman dari biji\n"
    "  - Pentingnya bekerja sama\n"
    "  - Keajaiban alam musim semi\n"
    "\n"
    "Sempurna untuk anak usia 6-8 tahun yang suka alam dan sains dasar!\n"
    "Tonton sampai habis dan temukan kejutan di akhir cerita!"
),
'bsl03_id': (
    "Hami si hamster pemberani punya kapal selam bernama 'Gelembung'. Hari ini ia nekat menyelami lautan biru yang penuh misteri!\n"
    "Akankah Hami menemukan keberanian yang ia cari di dasar laut?\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Arti keberanian yang sesungguhnya\n"
    "  - Pentingnya mencoba hal baru\n"
    "  - Keindahan dunia bawah laut\n"
    "\n"
    "Untuk anak usia 6-8 tahun. Yuk, berani bersama Hami!\n"
    "Jangan lewatkan kuis seru di akhir video!"
),
'bsl04_id': (
    "Di Kerajaan Biji Pohon Ek, Duri, Sori, dan Bami sedang bersiap untuk pesta ulang tahun istimewa!\n"
    "Tapi semuanya harus bekerja sama agar pesta berjalan sempurna. Bisakah mereka melakukannya?\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Pentingnya bekerja sama (gotong royong)\n"
    "  - Cara berbagi tugas dengan teman\n"
    "  - Kebahagiaan merayakan bersama\n"
    "\n"
    "Cocok untuk anak usia 6-7 tahun!\n"
    "Saksikan pesta yang tak terlupakan di video ini!"
),
'bsl05_id': (
    "Di hari hujan yang deras, keluarga kelinci Duri dan Turi mendapat kejutan yang tak terduga!\n"
    "Bagaimana keluarga mereka saling membantu dan melewati hari istimewa ini bersama?\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Arti keluarga dan saling membantu\n"
    "  - Menghadapi situasi tak terduga dengan tenang\n"
    "  - Kehangatan cinta keluarga\n"
    "\n"
    "Untuk anak usia 6-7 tahun yang suka cerita keluarga!\n"
    "Ikuti petualangan hangat keluarga kelinci sekarang!"
),
'bsl07_id': (
    "Echo si gajah ingin menjelajahi hutan, tapi ia tidak tahu harus memakai pakaian apa!\n"
    "Dimulailah petualangan Echo mencari pakaian penjelajah yang tepat — dan pelajaran berharga pun menanti!\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Cara memilih pakaian sesuai kegiatan\n"
    "  - Persiapan sebelum berpetualang\n"
    "  - Percaya diri mencoba hal baru\n"
    "\n"
    "Cocok untuk anak usia 6-7 tahun!\n"
    "Bantu Echo menemukan pakaian yang tepat!"
),
'saram18_id': (
    "Semut Ami yang rapi dan Lebah Bubi yang lincah sangat berbeda satu sama lain.\n"
    "Tapi suatu hari, mereka saling mengundang ke rumah masing-masing... dan keajaiban pun terjadi!\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Cara mengundang dan menerima tamu dengan sopan\n"
    "  - Menghargai perbedaan teman\n"
    "  - Persahabatan yang indah meski berbeda\n"
    "\n"
    "Untuk anak usia 6-7 tahun. Saling menghargai itu indah!\n"
    "Temukan kejutan persahabatan Ami dan Bubi!"
),
'id01': (
    "Di Desa Pelangi, Lintang dan Bayu mendengar bisikan misterius dari Hutan Bisik...\n"
    "Ada rahasia tersembunyi di sana — dan mereka memberanikan diri untuk mencari tahu!\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Keberanian menghadapi misteri\n"
    "  - Persahabatan yang kuat\n"
    "  - Keajaiban alam Indonesia\n"
    "\n"
    "Dongeng anak Indonesia yang penuh imajinasi dan petualangan!\n"
    "Temukan rahasia Hutan Bisik bersama Lintang dan Bayu!"
),
'space01_id': (
    "Mongsili si monyet dan Koko si gajah menaiki roket dan terbang ke luar angkasa!\n"
    "Mereka melihat satelit, planet Venus, dan bahkan bertemu Kelinci Bulan di sisi gelap bulan!\n"
    "\n"
    "Dalam cerita ini anak-anak akan belajar:\n"
    "  - Pengenalan tata surya (satelit, Venus, Bulan)\n"
    "  - Keberanian bertualang bersama teman\n"
    "  - Imajinasi dan mimpi yang tak terbatas\n"
    "\n"
    "Untuk anak usia 5-8 tahun yang suka luar angkasa!\n"
    "Ikuti petualangan seru Mongsili dan Koko ke luar angkasa!"
),
}

TAGS = {
'bsl02_id': '#dongenganak #ceritaanak #belajarsains #musimbunga #bijibunga #kelas1 #tumbuhan #alam #anakIndonesia',
'bsl03_id': '#dongenganak #ceritaanak #kapalselam #bawahlautan #berani #hamster #kelas1 #petualangan #anak',
'bsl04_id': '#dongenganak #ceritaanak #pestaulangtahun #kerjasama #tupai #kelas1 #kerajaanhutan #belajarbersama',
'bsl05_id': '#dongenganak #ceritaanak #keluarga #hujan #kelinci #kelas1 #salingmembantu #kehangatan',
'bsl07_id': '#dongenganak #ceritaanak #gajah #petualangan #kelas1 #belajarmemilih #eksplorasi #pakaianhutan',
'saram18_id': '#dongenganak #ceritaanak #semut #lebah #persahabatan #kelas1 #menghargaiperbedaan #undangan',
'id01': '#dongenganak #dongengIndonesia #ceritaanak #hutanmisterius #petualangan #burung #persahabatan #Indonesia',
'space01_id': '#dongenganak #ceritaanak #luarangkasa #monyet #gajah #bulan #antariksa #petualanganruang #kelas1',
}

lines = []
lines.append('유튜브 업로드용 — 인도네시아어(id) 시리즈')
lines.append('생성일: 2026-04-05')
lines.append('=' * 65)
lines.append('')

for i, d in enumerate(ORDER, 1):
    with open(f'output/{d}/story.json', encoding='utf-8') as f:
        s = json.load(f)
    meta = s.get('meta', {})
    title = meta.get('story_title', '')
    yt_title = YT_TITLE_FIX.get(d, meta.get('youtube_title', title))

    lines.append(f'[{i}] {title}')
    lines.append('-' * 65)
    lines.append('')
    lines.append('[제목]')
    lines.append(yt_title)
    lines.append('')
    lines.append('[설명]')
    lines.append(DESCS[d])
    lines.append('')
    lines.append('[해시태그]')
    lines.append(TAGS[d])
    lines.append('')
    lines.append('=' * 65)
    lines.append('')

out = '\n'.join(lines)
with open('output/youtube_upload_id_series.txt', 'w', encoding='utf-8') as f:
    f.write(out)
print(f'저장 완료: output/youtube_upload_id_series.txt  ({len(out.encode("utf-8"))} bytes)')
