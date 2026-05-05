from django.db import models

class UserRole:
    ADMIN = 'Admin'
    MANAGER = 'Manager'
    EMPLOYEE = 'Employee'

class Employee(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    employee_id = models.CharField(max_length=50, unique=True)
    email_id = models.EmailField()
    phone_no = models.CharField(max_length=20)
    organization = models.ForeignKey('orgSetup.OrganizationProfile', db_index=True, on_delete=models.CASCADE)
    department = models.ForeignKey('core.Department', null=True, blank=True, on_delete=models.SET_NULL)
    designation = models.ForeignKey('core.Designation', null=True, blank=True, on_delete=models.SET_NULL)
    branch = models.ForeignKey('core.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    work_shift = models.ForeignKey('core.WorkShift', null=True, blank=True, on_delete=models.SET_NULL)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return self.get_full_name()

class Department(models.Model):
    name = models.CharField(max_length=100)

class Designation(models.Model):
    name = models.CharField(max_length=100)

class Branch(models.Model):
    name = models.CharField(max_length=100)

class WorkShift(models.Model):
    name = models.CharField(max_length=100)
