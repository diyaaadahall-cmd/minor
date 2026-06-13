from django.db import models
from django.contrib.auth.models import User

class Note(models.Model):
    subject = models.CharField(max_length=100)
    pdf = models.FileField(upload_to='notes/')

    def __str__(self):
        return self.subject


class NoteProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name='progress_records')
    pages_read = models.PositiveIntegerField(default=0)
    total_pages = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'note')

    def __str__(self):
        return f'{self.user.username} - {self.note.subject}: {self.pages_read}/{self.total_pages}'

