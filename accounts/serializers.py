from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User, UserModulePermission, MODULE_CHOICES


class UserModulePermissionSerializer(serializers.ModelSerializer):
    module_label = serializers.CharField(source='get_module_display', read_only=True)

    class Meta:
        model = UserModulePermission
        fields = ['module', 'module_label', 'can_read', 'can_write']

    def validate(self, data):
        if data.get('can_write') and not data.get('can_read'):
            data['can_read'] = True
        return data


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    permissions = UserModulePermissionSerializer(source='module_permissions', many=True, read_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'employee_code', 'email', 'first_name',
                  'last_name', 'full_name', 'phone', 'department', 'role',
                  'is_active', 'permissions', 'created_at']
        read_only_fields = ['id', 'created_at']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = 'employee_code'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee_code'] = serializers.CharField()
        self.fields.pop('username', None)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['employee_code'] = user.employee_code
        token['name'] = user.get_full_name()
        token['role'] = user.role
        return token

    def validate(self, attrs):
        employee_code = attrs.get('employee_code')
        password = attrs.get('password')

        try:
            user = User.objects.get(employee_code=employee_code)
        except User.DoesNotExist:
            raise serializers.ValidationError('Invalid employee code or password')

        if not user.check_password(password):
            raise serializers.ValidationError('Invalid employee code or password')

        if not user.is_active:
            raise serializers.ValidationError('User account is disabled')

        refresh = self.get_token(user)

        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data
        }


# ─── Admin Serializers ────────────────────────────────────────────────────────

class AdminUserCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    permissions = UserModulePermissionSerializer(many=True, required=False, write_only=True)

    class Meta:
        model = User
        fields = ['employee_code', 'username', 'email', 'first_name', 'last_name',
                  'phone', 'department', 'role', 'password', 'permissions']

    def validate_employee_code(self, value):
        if User.objects.filter(employee_code=value).exists():
            raise serializers.ValidationError("Employee code already exists.")
        return value

    def validate(self, data):
        if not data.get('username'):
            data['username'] = data['employee_code']
        return data

    def create(self, validated_data):
        permissions_data = validated_data.pop('permissions', [])
        password = validated_data.pop('password')

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        if user.role == 'ADMIN':
            for module_key, _ in MODULE_CHOICES:
                UserModulePermission.objects.create(
                    user=user, module=module_key, can_read=True, can_write=True
                )
        else:
            for perm_data in permissions_data:
                if perm_data.get('can_write') and not perm_data.get('can_read'):
                    perm_data['can_read'] = True
                UserModulePermission.objects.create(user=user, **perm_data)

        return user


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    permissions = UserModulePermissionSerializer(many=True, required=False)
    password = serializers.CharField(write_only=True, min_length=6, required=False)

    class Meta:
        model = User
        fields = ['employee_code', 'username', 'email', 'first_name', 'last_name',
                  'phone', 'department', 'role', 'is_active', 'password', 'permissions']
        extra_kwargs = {
            'employee_code': {'required': False},
        }

    def validate_employee_code(self, value):
        if self.instance and self.instance.employee_code != value:
            if User.objects.filter(employee_code=value).exists():
                raise serializers.ValidationError("Employee code already exists.")
        return value

    def update(self, instance, validated_data):
        permissions_data = validated_data.pop('permissions', None)
        password = validated_data.pop('password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if permissions_data is not None:
            instance.module_permissions.all().delete()
            if instance.role == 'ADMIN':
                for module_key, _ in MODULE_CHOICES:
                    UserModulePermission.objects.create(
                        user=instance, module=module_key, can_read=True, can_write=True
                    )
            else:
                for perm_data in permissions_data:
                    if perm_data.get('can_write') and not perm_data.get('can_read'):
                        perm_data['can_read'] = True
                    UserModulePermission.objects.create(user=instance, **perm_data)

        return instance
