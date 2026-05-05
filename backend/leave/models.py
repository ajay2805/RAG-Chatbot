from django.db import models

class Leave(models.Model):
    employee = models.ForeignKey('core.Employee', on_delete=models.CASCADE)
    organization = models.ForeignKey('orgSetup.OrganizationProfile', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='Pending')
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.TextField()
    leave_type = models.CharField(max_length=50)
