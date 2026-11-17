from django.db import models


class AppSetting(models.Model):
    """Settings that can be changed in the browser (key -> text value)."""
    key = models.CharField(max_length=50, primary_key=True)
    value = models.TextField(blank=True)

    def __str__(self):
        return f"{self.key} = {self.value}"
