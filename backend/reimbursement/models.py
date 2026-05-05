from django.db import models
class Reimbursement(models.Model):
    employee = models.ForeignKey('core.Employee', on_delete=models.CASCADE)
    organization = models.ForeignKey('orgSetup.OrganizationProfile', on_delete=models.CASCADE)
    reimbursement_status = models.CharField(max_length=20, default='Pending')
