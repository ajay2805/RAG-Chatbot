from django.db import models

class TimeLog(models.Model):
    organization = models.ForeignKey('orgSetup.OrganizationProfile', on_delete=models.CASCADE)
    employee = models.ForeignKey('core.Employee', on_delete=models.CASCADE)
    punch_date = models.DateField()
    work_status = models.CharField(max_length=50)
    punch_in_time = models.TimeField(null=True, blank=True)
    punch_out_time = models.TimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
