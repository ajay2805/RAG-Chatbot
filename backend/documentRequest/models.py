from django.db import models
class DocumentRequest(models.Model):
    employee = models.ForeignKey('core.Employee', on_delete=models.CASCADE)
    organization = models.ForeignKey('orgSetup.OrganizationProfile', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='Pending')
