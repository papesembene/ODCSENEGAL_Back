"""Interview members may hold several roles (e.g. validator and coach) on the same account.

`interview_role` stays the primary role for backward compatibility; `interview_roles` lists every role.
Accounts created before multi-role support only have `interview_role`.
"""


def member_roles(profile_data):
    profile = profile_data or {}
    primary = profile.get("interview_role")
    roles = [primary] if primary else []
    roles += [role for role in profile.get("interview_roles") or [] if isinstance(role, str)]
    return list(dict.fromkeys(roles))


def has_role(user, role):
    profile = getattr(user, "profile_data", None) or {}
    return profile.get("admin_scope") == "interview_member" and role in member_roles(profile)


def role_query(role):
    """Raw Mongo condition matching members holding `role`, as primary or additional role."""
    return {"$or": [{"profile_data.interview_role": role}, {"profile_data.interview_roles": role}]}
