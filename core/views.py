import re

from django.contrib.auth import authenticate, login
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .llm import LLMUnavailable, answer_from_context
from .models import Note, NoteProgress

def home(request):
    if request.method == "POST":

        print("LOGIN ATTEMPT:", request.POST)

        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('dashboard')

        return render(request, 'core/login.html', {'error': 'Invalid credentials'})

    return render(request, 'core/login.html')


def dashboard(request):
    subject_progress = {}
    total_pages_read = 0
    total_pages_available = 0

    notes = Note.objects.all().order_by('subject', 'id')
    progress_by_note_id = {}
    if request.user.is_authenticated:
        progress_by_note_id = {
            progress.note_id: progress
            for progress in NoteProgress.objects.filter(user=request.user, note__in=notes)
        }

    for note in notes:
        subject_key = note.subject.strip().lower()
        total_pages = _get_pdf_page_count(note)
        progress = progress_by_note_id.get(note.id)
        pages_read = min(progress.pages_read, total_pages) if progress else 0

        subject_data = subject_progress.setdefault(subject_key, {
            'pages_read': 0,
            'total_pages': 0,
            'pdf_count': 0,
        })
        subject_data['pages_read'] += pages_read
        subject_data['total_pages'] += total_pages
        subject_data['pdf_count'] += 1

        total_pages_read += pages_read
        total_pages_available += total_pages

    return render(request, 'core/dashboard.html', {
        'subject_progress': subject_progress,
        'total_pages_read': total_pages_read,
        'total_pages_available': total_pages_available,
        'subjects_with_notes': len(subject_progress),
    })


def subject_notes(request, subject_name):
    notes = Note.objects.filter(subject__iexact=subject_name).order_by('id')
    selected_note = notes.first()
    note_progress = {}

    if request.user.is_authenticated:
        for progress in NoteProgress.objects.filter(user=request.user, note__in=notes):
            note_progress[str(progress.note_id)] = {
                'pages_read': progress.pages_read,
                'total_pages': progress.total_pages,
            }

    return render(request, 'core/subject_notes.html', {
        'subject_name': subject_name,
        'notes': notes,
        'selected_note': selected_note,
        'note_progress': note_progress,
    })


def _get_pdf_page_count(note):
    try:
        from pypdf import PdfReader
    except ImportError:
        return 0

    try:
        reader = PdfReader(note.pdf.path)
        return len(reader.pages)
    except Exception:
        return 0


def _extract_pdf_text(pdf_path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(pdf_path)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages)
    except Exception:
        return ""


def _find_relevant_context(pdf_text, question, max_chars=4500):
    normalized_text = re.sub(r'\s+', ' ', pdf_text).strip()
    if not normalized_text:
        return ""

    question_words = {
        word for word in re.findall(r'[a-zA-Z]{3,}', question.lower())
        if word not in {'what', 'when', 'where', 'which', 'about', 'from', 'that', 'this', 'with', 'into', 'your', 'does'}
    }

    chunks = re.split(r'(?<=[.!?])\s+', normalized_text)
    if not chunks:
        chunks = [normalized_text]

    ranked_chunks = sorted(
        chunks,
        key=lambda chunk: sum(1 for word in question_words if word in chunk.lower()),
        reverse=True,
    )

    best_chunks = [chunk for chunk in ranked_chunks[:4] if chunk.strip()]
    context = " ".join(best_chunks).strip()

    if not context:
        context = normalized_text[:max_chars]

    if len(context) > max_chars:
        context = context[:max_chars].rsplit(' ', 1)[0]

    return context


def _find_relevant_answer(pdf_text, question):
    normalized_text = re.sub(r'\s+', ' ', pdf_text).strip()
    if not normalized_text:
        return "I could not read text from this PDF. It may be scanned as images or protected."

    context = _find_relevant_context(pdf_text, question, max_chars=1400)
    answer = context or normalized_text[:1000]

    if len(answer) > 1400:
        answer = answer[:1400].rsplit(' ', 1)[0] + "..."

    question_words = {
        word for word in re.findall(r'[a-zA-Z]{3,}', question.lower())
        if word not in {'what', 'when', 'where', 'which', 'about', 'from', 'that', 'this', 'with', 'into', 'your', 'does'}
    }

    if question_words and sum(1 for word in question_words if word in answer.lower()) == 0:
        return "I could not find a direct match in the PDF. Here is a nearby excerpt I can read:\n\n" + answer

    return answer


def _answer_pdf_question(pdf_text, question, note_name):
    if not re.sub(r'\s+', ' ', pdf_text).strip():
        return (
            "I could not read text from this PDF. It may be scanned as images or protected.",
            "fallback",
        )

    context = _find_relevant_context(pdf_text, question)
    fallback_answer = _find_relevant_answer(pdf_text, question)

    if not context:
        return fallback_answer, "fallback"

    try:
        return answer_from_context(question, context, note_name), "open_llm"
    except LLMUnavailable:
        return fallback_answer, "fallback"


def pdf_chat(request, subject_name):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required.'}, status=405)

    question = request.POST.get('question', '').strip()
    note_id = request.POST.get('note_id')

    if not question:
        return JsonResponse({'error': 'Please ask a question first.'}, status=400)

    notes = Note.objects.filter(subject__iexact=subject_name)
    if note_id:
        note = get_object_or_404(notes, id=note_id)
    else:
        note = notes.order_by('id').first()
        if note is None:
            raise Http404("No PDFs uploaded for this subject.")

    pdf_text = _extract_pdf_text(note.pdf.path)
    note_name = note.pdf.name.split('/')[-1]
    answer, answer_source = _answer_pdf_question(pdf_text, question, note_name)

    return JsonResponse({
        'answer': answer,
        'answer_source': answer_source,
        'note': note_name,
    })


@require_POST
def site_chatbot(request):
    question = request.POST.get('question', '').strip()
    if not question:
        return JsonResponse({'error': 'Please ask a question first.'}, status=400)

    return JsonResponse({
        'answer': _answer_site_question(question, request.user),
    })


def _answer_site_question(question, user):
    lowered_question = question.lower()
    notes = list(Note.objects.all().order_by('subject', 'id'))
    subjects = sorted({note.subject.strip() for note in notes}, key=str.lower)
    subject_lookup = {subject.lower(): subject for subject in subjects}

    if any(word in lowered_question for word in ['upload', 'add pdf', 'add note', 'new pdf']):
        return (
            "To upload a PDF, open /admin/, log in, choose Notes, click Add Note, "
            "enter the exact subject name from the dashboard, choose the PDF, and save. "
            "After that, the PDF appears when you open that subject."
        )

    if any(word in lowered_question for word in ['available', 'availability', 'have', 'uploaded', 'notes', 'pdf']):
        requested_subject = _find_subject_in_question(lowered_question, subject_lookup)
        if requested_subject:
            matching_notes = [note for note in notes if note.subject.strip().lower() == requested_subject.lower()]
            if not matching_notes:
                return f"No PDFs are uploaded for {requested_subject} yet."

            filenames = ", ".join(note.pdf.name.split('/')[-1] for note in matching_notes)
            return f"{requested_subject} has {len(matching_notes)} PDF(s) available: {filenames}."

        if not subjects:
            return "No PDFs have been uploaded yet."

        subject_lines = []
        for subject in subjects:
            count = sum(1 for note in notes if note.subject.strip().lower() == subject.lower())
            subject_lines.append(f"{subject} ({count} PDF{'s' if count != 1 else ''})")
        return "Available note subjects: " + "; ".join(subject_lines) + "."

    if any(word in lowered_question for word in ['progress', 'read', 'studied', 'page', 'pages']):
        return _site_progress_answer(user, notes, lowered_question, subject_lookup)

    if any(word in lowered_question for word in ['chatbot', 'chat bot', 'ai', 'cost', 'pay', 'paid']):
        return (
            "There are two local chat features. The subject PDF chat reads the selected PDF and searches its text. "
            "This sidebar assistant answers questions about the website, available notes, uploads, and reading progress. "
            "Neither one uses a paid AI API right now."
        )

    if any(word in lowered_question for word in ['how', 'use', 'open', 'view', 'website', 'site']):
        return (
            "Use the semester dropdown to browse courses. Click Launch Subject Study to open a subject, "
            "view its PDFs, track pages read, and ask PDF-specific questions. Use this sidebar assistant for "
            "general questions about notes, availability, progress, and uploads."
        )

    return (
        "I can help with this website, uploaded notes, PDF availability, reading progress, uploads, "
        "and how the PDF chatbot works. Try asking: 'Which notes are available?' or 'What is my progress?'"
    )


def _find_subject_in_question(lowered_question, subject_lookup):
    for subject_key, subject in subject_lookup.items():
        if subject_key in lowered_question:
            return subject

    question_words = set(re.findall(r'[a-zA-Z]{3,}', lowered_question))
    best_subject = None
    best_score = 0
    for subject_key, subject in subject_lookup.items():
        subject_words = set(re.findall(r'[a-zA-Z]{3,}', subject_key))
        score = len(question_words & subject_words)
        if score > best_score:
            best_score = score
            best_subject = subject

    if best_score > 0:
        return best_subject

    return None


def _site_progress_answer(user, notes, lowered_question, subject_lookup):
    if not user.is_authenticated:
        return "Reading progress is saved only after login. Please log in, open a PDF, and move through pages to track progress."

    requested_subject = _find_subject_in_question(lowered_question, subject_lookup)
    filtered_notes = [
        note for note in notes
        if requested_subject is None or note.subject.strip().lower() == requested_subject.lower()
    ]

    if not filtered_notes:
        return f"No PDFs are uploaded for {requested_subject} yet." if requested_subject else "No PDFs are uploaded yet."

    progress_records = {
        progress.note_id: progress
        for progress in NoteProgress.objects.filter(user=user, note__in=filtered_notes)
    }

    pages_read = 0
    total_pages = 0
    for note in filtered_notes:
        note_total_pages = _get_pdf_page_count(note)
        progress = progress_records.get(note.id)
        note_pages_read = min(progress.pages_read, note_total_pages) if progress else 0
        pages_read += note_pages_read
        total_pages += note_total_pages

    percent = round((pages_read / total_pages) * 100, 1) if total_pages else 0
    scope = requested_subject if requested_subject else "all uploaded PDFs"
    return f"Your reading progress for {scope} is {pages_read}/{total_pages} pages ({percent}%)."


@require_POST
def update_note_progress(request, subject_name):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required to save progress.'}, status=403)

    note_id = request.POST.get('note_id')
    current_page = request.POST.get('current_page')
    total_pages = request.POST.get('total_pages')

    try:
        current_page = int(current_page)
        total_pages = int(total_pages)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid page progress.'}, status=400)

    note = get_object_or_404(Note, id=note_id, subject__iexact=subject_name)
    actual_total_pages = _get_pdf_page_count(note) or total_pages
    current_page = max(0, min(current_page, actual_total_pages))

    progress, _ = NoteProgress.objects.get_or_create(user=request.user, note=note)
    progress.total_pages = actual_total_pages
    progress.pages_read = max(progress.pages_read, current_page)
    progress.save()

    return JsonResponse({
        'pages_read': progress.pages_read,
        'total_pages': progress.total_pages,
        'percent': round((progress.pages_read / progress.total_pages) * 100, 1) if progress.total_pages else 0,
    })
