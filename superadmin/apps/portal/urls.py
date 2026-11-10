"""Customer portal URLs. Mounted at the root of PORTAL_HOST (config.portal_urls), at /portal/ for local preview,
and under /client-portal/preview/<member>/ for staff "Preview as customer" (namespace portal_preview).

Staff preview mounts ``workspace_patterns`` only: the sign-in routes, the installable-app routes (manifest,
service worker, offline page) and the push notification routes exist on the customer surface alone."""

from django.urls import path

from .views import auth, customer, pwa
from .views import push as push_views

app_name = "portal"

auth_patterns = [
    # Access
    path("sign-in/", auth.login_view, name="login"),
    path("sign-in/verify/", auth.otp_verify, name="otp_verify"),
    path("sign-out/", auth.logout_view, name="logout"),
    path("forgot-password/", auth.forgot_password, name="forgot"),
    path("reset/<uidb64>/<token>/", auth.reset_password, name="reset_password"),
    path("invitation/<str:token>/", auth.invitation, name="invitation"),
]

workspace_patterns = [
    # Your account: one page per section (Notification preferences is under notifications/).
    path("account/", customer.account, name="account"),
    path("account/security/", customer.account_security, name="account_security"),
    path("account/security/two-step/", auth.otp_setup, name="otp_setup"),
    path("account/device/", customer.account_device, name="account_device"),
    path("account/install/", customer.account_install, name="account_install"),
    path("", customer.dashboard, name="home"),
    path("challenges/", customer.challenges, name="challenges"),
    path("challenges/<int:pk>/", customer.challenge, name="challenge"),
    path("challenges/<int:pk>/discuss/", customer.challenge_discuss, name="challenge_discuss"),
    path("challenges/<int:pk>/briefs/<int:brief_pk>/review/", customer.brief_review, name="brief_review"),
    path("projects/<int:pk>/", customer.project, name="project"),
    path("projects/<int:pk>/export.csv", customer.project_export, name="project_export"),
    path("projects/<int:pk>/changes/new/", customer.change_new, name="change_new"),
    path("changes/<int:pk>/", customer.change, name="change"),
    path("milestones/<int:pk>/", customer.milestone, name="milestone"),
    path("deliverables/<int:pk>/", customer.deliverable, name="deliverable"),
    path("versions/<int:pk>/approve/", customer.version_approve, name="version_approve"),
    path("versions/<int:pk>/changes/", customer.version_changes, name="version_changes"),
    path("versions/<int:pk>/accept/", customer.version_accept, name="version_accept"),
    path("questions/", customer.questions, name="questions"),
    path("questions/<int:pk>/", customer.question, name="question"),
    path("updates/<int:pk>/", customer.update, name="update"),
    path("files/", customer.files, name="files"),
    path("files/upload/", customer.file_upload, name="file_upload"),
    path("files/<int:pk>/", customer.file, name="file"),
    path("files/versions/<int:pk>/download/", customer.file_download, name="file_download"),
    path("activity/", customer.activity, name="activity"),
    path("search/", customer.search, name="search"),
    path("assistant/<str:activity>/", customer.assistant, name="assistant"),
    # Notifications
    path("notifications/", customer.notifications_list, name="notifications"),
    path("notifications/read-all/", customer.notifications_read_all, name="notifications_read_all"),
    path("notifications/preferences/", customer.notification_preferences, name="notification_preferences"),
    path("notifications/<int:pk>/open/", customer.notification_open, name="notification_open"),
]

# Installable app (ADR-056, Phase 1). Public; the worker sits at the portal root so its scope covers the portal.
pwa_patterns = [
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
]

# Push notifications (ADR-056, Phase 2). The member's own devices only; never in staff preview.
push_patterns = [
    path("push/subscribe/", push_views.subscribe, name="push_subscribe"),
    path("push/unsubscribe/", push_views.unsubscribe, name="push_unsubscribe"),
    path("push/test/", push_views.send_test, name="push_test"),
    path("push/renew/", push_views.renew, name="push_renew"),
]

urlpatterns = auth_patterns + pwa_patterns + push_patterns + workspace_patterns
