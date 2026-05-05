from django.db import models
class TimeSheet(models.Model):
    employee = models.ForeignKey('core.Employee', on_delete=models.CASCADE)
    organization = models.ForeignKey('orgSetup.OrganizationProfile', on_delete=models.CASCADE)
    manager_approval = models.CharField(max_length=20, default='Pending')
