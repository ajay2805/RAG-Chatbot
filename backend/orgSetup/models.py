from django.db import models

class OrganizationProfile(models.Model):
    organization_name = models.CharField(max_length=200)

    def __str__(self):
        return self.organization_name

class EmployeeIDPrefix(models.Model):
    organization = models.ForeignKey(OrganizationProfile, on_delete=models.CASCADE)
    prefix = models.CharField(max_length=10)

class ReportingTree(models.Model):
    organization = models.ForeignKey(OrganizationProfile, on_delete=models.CASCADE)
    manager = models.ForeignKey('core.Employee', related_name='reportees', on_delete=models.CASCADE)
    reportee = models.ForeignKey('core.Employee', related_name='managers', on_delete=models.CASCADE)

class WeekendSettings(models.Model):
    organization = models.ForeignKey(OrganizationProfile, on_delete=models.CASCADE)
    weekends = models.JSONField(default=list)
