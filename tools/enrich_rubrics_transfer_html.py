# -*- coding: utf-8 -*-
"""Добавляет в rubrics-transfer-links.html встроенные промпты и правила с якорями."""
import html
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "rubrics-transfer-links.html"


def esc(t: str) -> str:
    return html.escape(t)


def read(path: str) -> str:
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def pre_block(text: str) -> str:
    return f"<pre>{esc(text.strip())}</pre>\n"


def build_rules_html() -> str:
    rules_files = [
        ("global-rules-base", "prompts/base-system-kie.md", "Базовый системный промпт (все рубрики)"),
        ("global-rules-facts", "knowledge/nds-2026-facts.md", "База фактов НДС 2026"),
        ("global-rules-text-check", "docs/workflows/text-double-check.md", "Двойная проверка текста"),
        ("global-rules-visual-check", "docs/workflows/visual-prompt-check.md", "Проверка промпта к визуалу"),
        ("global-rules-pre-check", "docs/workflows/pre-generation-checklist.md", "Pre-check перед генерацией"),
        ("global-rules-visual-decision", "docs/workflows/visual-decision.md", "Выбор image или video"),
        ("global-rules-kie-text", "docs/models/kie-text-model.md", "Модели текста KIE"),
        ("global-rules-kie-visual", "docs/models/kie-visual-rules.md", "Модели и форматы визуала KIE"),
    ]
    rules_html = (
        '<h2 id="rules-full">Общие правила проекта (полный текст)</h2>\n'
        '<div class="note">Ниже — все утверждённые общие правила. '
        "Используйте вместе с базовым промптом для любой рубрики.</div>\n"
    )
    for sid, path, title in rules_files:
        content = read(path)
        if not content:
            continue
        rules_html += (
            f'<div class="card" id="{sid}"><h3>{esc(title)}</h3>'
            f'<p class="small">Файл в проекте: <code>{esc(path)}</code></p>'
        )
        rules_html += pre_block(content)
        rules_html += '<p><a href="#rules-full">Наверх к правилам</a></p></div>\n'
    return rules_html


def build_prompts_html() -> str:
    rubrics = [
        (
            "razbor",
            [
                ("razbor-prompt-text", "prompts/razbor.md", "Промпт к тексту поста"),
            ],
            None,
            None,
        ),
        (
            "law_review",
            [
                ("law-review-prompt-text", "prompts/law_review.md", "Промпт к тексту поста"),
            ],
            None,
            None,
        ),
        (
            "case",
            [
                ("case-prompt-text", "prompts/case.md", "Промпт к тексту поста"),
            ],
            "output/case-post-usn-22-vychet-visual-prompt.txt",
            "output/article-cover-case-usn-22-vychet-prompt-v2.txt",
        ),
        (
            "expert",
            [
                ("expert-prompt-text", "prompts/expert.md", "Промпт к тексту поста (базовый)"),
                ("expert-prompt-text-adv", "prompts/expert-advanced-template.md", "Промпт к тексту поста (расширенный)"),
                ("expert-prompt-article", "prompts/expert-article-advanced-template.md", "Промпт к тексту статьи"),
            ],
            "output/expert-post-zero-rate-nds-visual-prompt-v4-color-restored.txt",
            "output/expert-article-zero-rate-nds-cover-prompt.txt",
        ),
        (
            "calculation",
            [
                ("calculation-prompt-text", "prompts/calculation.md", "Промпт к тексту поста (базовый)"),
                (
                    "calculation-prompt-text-adv",
                    "prompts/calculation-advanced-template.md",
                    "Промпт к тексту поста (расчёт)",
                ),
            ],
            "output/calculation-post-separate-accounting-medical-and-22-visual-prompt.txt",
            "output/calculation-article-separate-accounting-medical-and-22-cover-prompt.txt",
        ),
        (
            "serial-yumor",
            [
                ("serial-yumor-prompt-text", "prompts/serial.md", "Промпт serial (базовый)"),
                ("serial-yumor-prompt-adv", "prompts/serial-yumor-advanced-template.md", "Промпт serial+yumor (сезон)"),
                ("serial-yumor-prompt-comic", "prompts/serial-comic-frames.md", "Промпт к комиксу / кадрам"),
                ("serial-yumor-prompt-character", "docs/characters/alina.md", "Персонаж Алина"),
            ],
            "output/serial-yumor-s1-ep01-visual-prompt-v2.txt",
            None,
        ),
        (
            "poll",
            [("poll-prompt-text", "prompts/poll.md", "Промпт к тексту поста")],
            "output/poll-post-nds-reporting-visual-prompt.txt",
            None,
        ),
        (
            "checklist",
            [("checklist-prompt-text", "prompts/checklist.md", "Промпт к тексту поста")],
            "output/checklist-post-vychet-confirmation-visual-prompt.txt",
            None,
        ),
        (
            "article-announcement",
            [
                (
                    "article-announcement-prompt-text",
                    "prompts/article_announcement.md",
                    "Промпт к тексту поста-анонса",
                ),
            ],
            "output/article-announcement-separate-accounting-medical-and-22-visual-prompt.txt",
            None,
        ),
    ]

    prompts_html = (
        '<h2 id="prompts-all">Промпты по рубрикам (полный текст)</h2>\n'
        '<div class="note">Кликабельные якоря из карточек рубрик ведут сюда. '
        "Всё можно копировать из этого файла без доступа к папке проекта.</div>\n"
    )

    for card_id, text_files, vis_path, cover_path in rubrics:
        prompts_html += f'<div class="card" id="{card_id}-prompts"><h3>Промпты: {esc(card_id)}</h3>\n'
        for sid, path, title in text_files:
            content = read(path)
            prompts_html += f'<h4 id="{sid}">{esc(title)}</h4><p class="small"><code>{esc(path)}</code></p>'
            prompts_html += pre_block(content)
        if vis_path:
            content = read(vis_path)
            prefix = card_id.replace("_", "-")
            sid = f"{prefix}-prompt-visual"
            prompts_html += (
                f'<h4 id="{sid}">Промпт к визуалу поста (утверждённый пример)</h4>'
                f'<p class="small"><code>{esc(vis_path)}</code></p>'
            )
            prompts_html += pre_block(content)
        if cover_path:
            content = read(cover_path)
            prefix = card_id.replace("_", "-")
            sid = f"{prefix}-prompt-cover"
            prompts_html += (
                f'<h4 id="{sid}">Промпт к обложке статьи (утверждённый пример)</h4>'
                f'<p class="small"><code>{esc(cover_path)}</code></p>'
            )
            prompts_html += pre_block(content)
        prompts_html += (
            f'<p><a href="#{card_id}">Вернуться к карточке {esc(card_id)}</a> · '
            f'<a href="#prompts-all">К списку промптов</a></p></div>\n'
        )
    return prompts_html


def main() -> None:
    text = OUT.read_text(encoding="utf-8")
    if 'id="rules-full"' in text:
        print("Already enriched, skip")
        return

    css_add = """
    .toc { background: #fffbeb; border: 1px solid #fcd34d; padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; }
    .toc a { display: inline-block; margin: 4px 12px 4px 0; }
    .prompt-section pre { max-height: none; font-size: 13px; }
    h4 { margin: 16px 0 8px; font-size: 16px; }
"""
    text = text.replace("ul { margin-top: 8px; }", "ul { margin-top: 8px; }" + css_add)

    old_note = (
        "В этом файле все ссылки кликабельные для стороннего пользователя: "
        "отдельно на текст и отдельно на изображение."
    )
    new_note = (
        old_note
        + " Промпты к тексту, визуалу и статьям — по якорям внутри файла (разделы ниже). "
        "Пути <code>prompts/...</code> в карточках — имена файлов в проекте; "
        "полный текст — по ссылкам «Промпт к тексту» / «Промпт к визуалу»."
    )
    text = text.replace(old_note, new_note)

    toc = """<div class="toc">
  <b>Быстрая навигация:</b>
  <a href="#rules-full">Все общие правила</a>
  <a href="#prompts-all">Все промпты рубрик</a>
  <a href="#razbor">razbor</a>
  <a href="#law_review">law_review</a>
  <a href="#case">case</a>
  <a href="#expert">expert</a>
  <a href="#calculation">calculation</a>
  <a href="#serial-yumor">serial</a>
  <a href="#poll">poll</a>
  <a href="#checklist">checklist</a>
  <a href="#article-announcement">article_announcement</a>
</div>
"""
    text = text.replace(
        "</div>\n\n  <h2>Проверенные рубрики</h2>",
        "</div>\n" + toc + "\n  <h2>Проверенные рубрики</h2>",
    )

    text = text.replace(
        '<h2>Общие ограничения и требования к постам</h2>',
        '<h2>Общие ограничения и требования к постам</h2>\n'
        '  <p><a href="#rules-full"><b>Открыть все общие правила (полный текст)</b></a> · '
        '<a href="#prompts-all"><b>Все промпты рубрик</b></a></p>',
    )

    text = text.replace(
        '<p><b>Нейросеть для визуала:</b> <code>Nano Banana Pro</code></p>\n'
        '    <div class="links">\n      <a href="#razbor-prompt-text">',
        '<p><b>Нейросеть для визуала:</b> <code>Nano Banana Pro</code></p>\n'
        '    <p class="small">Утверждённый файл visual-prompt для razbor в проекте не сохранялся — '
        'ориентир: описание в карточке + <a href="#global-rules-visual-check">правила визуала</a>.</p>\n'
        '    <div class="links">\n      <a href="#razbor-prompt-text">',
        1,
    )

    text = text.replace(
        '<p><b>Нейросеть для визуала:</b> <code>Nano Banana Pro</code></p>\n'
        '    <div class="links">\n      <a href="#law-review-prompt-text">',
        '<p><b>Нейросеть для визуала:</b> <code>Nano Banana Pro</code></p>\n'
        '    <p class="small">Утверждённый файл visual-prompt для law_review в проекте не сохранялся — '
        'ориентир: описание в карточке + <a href="#global-rules-visual-check">правила визуала</a>.</p>\n'
        '    <div class="links">\n      <a href="#law-review-prompt-text">',
        1,
    )

    replacements = [
        (
            '<div class="links">\n      <a href="#razbor-text">Ссылка на текст (внутри этого файла)</a>',
            '<div class="links">\n      <a href="#razbor-prompt-text">Промпт к тексту</a>\n'
            '      <a href="#razbor-text">Текст поста (пример)</a>',
        ),
        (
            '<div class="links">\n      <a href="#law-review-text">Ссылка на текст (внутри этого файла)</a>',
            '<div class="links">\n      <a href="#law-review-prompt-text">Промпт к тексту</a>\n'
            '      <a href="#law-review-text">Текст поста (пример)</a>',
        ),
        (
            """    <div class="links">
      <a href="#case-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/workers/nano/image_1780036976648_ql66lx.png\"""",
            """    <div class="links">
      <a href="#case-prompt-text">Промпт к тексту</a>
      <a href="#case-prompt-visual">Промпт к визуалу</a>
      <a href="#case-prompt-cover">Промпт к обложке статьи</a>
      <a href="#case-text">Текст поста</a>
      <a href="#case-article-text">Текст статьи</a>
      <a href="https://tempfile.aiquickdraw.com/workers/nano/image_1780036976648_ql66lx.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#expert-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/images/1780043189971-xukwc0p7f6s.png\"""",
            """    <div class="links">
      <a href="#expert-prompt-text">Промпт к тексту</a>
      <a href="#expert-prompt-text-adv">Промпт расширенный</a>
      <a href="#expert-prompt-article">Промпт к статье</a>
      <a href="#expert-prompt-visual">Промпт к визуалу</a>
      <a href="#expert-prompt-cover">Промпт к обложке</a>
      <a href="#expert-text">Текст поста</a>
      <a href="#expert-article-text">Текст статьи</a>
      <a href="https://tempfile.aiquickdraw.com/images/1780043189971-xukwc0p7f6s.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#calculation-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/p/381d7452647407f2406fcdb7b332654f_1_1780045541_5143.png\"""",
            """    <div class="links">
      <a href="#calculation-prompt-text">Промпт к тексту</a>
      <a href="#calculation-prompt-text-adv">Промпт расчёт</a>
      <a href="#calculation-prompt-visual">Промпт к визуалу</a>
      <a href="#calculation-prompt-cover">Промпт к обложке</a>
      <a href="#calculation-text">Текст поста</a>
      <a href="#calculation-article-text">Текст статьи</a>
      <a href="https://tempfile.aiquickdraw.com/p/381d7452647407f2406fcdb7b332654f_1_1780045541_5143.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#serial-yumor-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/p/dbece6f983707a84068ac13083e2321c_1_1780048411_7928.png\"""",
            """    <div class="links">
      <a href="#serial-yumor-prompt-adv">Промпт сезона</a>
      <a href="#serial-yumor-prompt-comic">Промпт комикса</a>
      <a href="#serial-yumor-prompt-visual">Промпт к визуалу</a>
      <a href="#serial-yumor-text">Текст поста</a>
      <a href="https://tempfile.aiquickdraw.com/p/dbece6f983707a84068ac13083e2321c_1_1780048411_7928.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#poll-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/images/1780048879929-of8iyactx3c.png\"""",
            """    <div class="links">
      <a href="#poll-prompt-text">Промпт к тексту</a>
      <a href="#poll-prompt-visual">Промпт к визуалу</a>
      <a href="#poll-text">Текст поста</a>
      <a href="https://tempfile.aiquickdraw.com/images/1780048879929-of8iyactx3c.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#checklist-text">Ссылка на пост (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/p/fbde260ffc37759b5a7042edf4aeebc4_1_1780049275_8246.png\"""",
            """    <div class="links">
      <a href="#checklist-prompt-text">Промпт к тексту</a>
      <a href="#checklist-prompt-visual">Промпт к визуалу</a>
      <a href="#checklist-text">Текст поста</a>
      <a href="https://tempfile.aiquickdraw.com/p/fbde260ffc37759b5a7042edf4aeebc4_1_1780049275_8246.png\"""",
        ),
        (
            """    <div class="links">
      <a href="#article-announcement-text">Ссылка на пост-анонс (внутри этого файла)</a>
      <a href="https://tempfile.aiquickdraw.com/p/66fcf0ae081e4ba32be0833d6d054b18_1_1780049696_4061.png\"""",
            """    <div class="links">
      <a href="#article-announcement-prompt-text">Промпт к тексту</a>
      <a href="#article-announcement-prompt-visual">Промпт к визуалу</a>
      <a href="#article-announcement-text">Текст поста-анонса</a>
      <a href="#calculation-article-text">Статья-источник (calculation)</a>
      <a href="https://tempfile.aiquickdraw.com/p/66fcf0ae081e4ba32be0833d6d054b18_1_1780049696_4061.png\"""",
        ),
    ]
    for old, new in replacements:
        if old not in text:
            print("WARN missing:", old[:60])
        text = text.replace(old, new)

    insert_marker = "  <h2>Тексты по ссылкам</h2>"
    text = text.replace(
        insert_marker,
        build_rules_html() + "\n" + build_prompts_html() + "\n" + insert_marker,
    )

    OUT.write_text(text, encoding="utf-8")
    print("OK", OUT.stat().st_size)


if __name__ == "__main__":
    main()
