# Team Observer

An independent Flutter app for read-only team observability in the collaborative UML platform. It does not depend on or modify `mobile/`, the generated Spring APIs, or UAP.

## What it can do

- Sign in and list diagrams the authenticated user can access.
- Read diagram classes/relations, members, the three chat channels, activity, digest, and AI settings.
- Receive foreground WebSocket events while a diagram is open; reconnect with bounded backoff and refetch REST state after reconnect.
- Store the server URL in preferences and the JWT in platform secure storage. Passwords are never persisted. GET response cache is memory-only with a 15-second lifetime.
- Handle FCM foreground messages and notification taps when Firebase is configured.

The app has no diagram editor, chat composer, AI request flow, or seen-marker action. Its only POST request is sign-in. WebSocket connections are receive-only. Chat and notification content is rendered as plain text; links are never opened.

## Run

```sh
cd mobile-observer
flutter pub get
flutter run
```

The login screen defaults to `http://10.0.2.2:8000` for an Android emulator. Change the server field for a phone (`http://<computer-lan-ip>:8000`) or production (`https://<domain>/api`). The backend must be reachable from the device. Use HTTPS for production; HTTP is enabled for direct local/LAN development.

## Read-only backend contract

The client uses `POST /auth/sign-in` and only these protected GET routes:

| Route | Displayed information |
|---|---|
| `/auth/me` | Current account and saved-session validation |
| `/diagrams` | Accessible diagram list |
| `/diagrams/{id}` | UML classes and relations |
| `/diagrams/{id}/members` | Team roster |
| `/diagrams/{id}/chat?channel=...` | Read-only chat (`diseno`, `desarrollo`, `test`) |
| `/diagrams/{id}/activity` | Activity history |
| `/diagrams/{id}/digest` | Changes since the existing visit marker; does not update it |
| `/diagrams/{id}/ai-settings` | AI enabled/edit state |

It never calls `POST /chat`, `POST /seen`, or diagram/member/deployment mutation routes. The JWT is sent as a bearer header for HTTP and as the `token` query parameter for the backend WebSocket, which is the backend's current socket contract. HTTP 401 or WebSocket close code 1008 signs the user out. WebSocket loss triggers REST refresh after reconnect.

## Push notifications

Push delivery is enabled for the Android observer app and the MongoDB platform backend. Notifications are generic; they never include chat text, UML names, personal details, prompts, or model output.

### Configure and run

1. Keep `google-services.json` in the repository root; it must include an Android Firebase app registered as `com.primerparcial.mobile_observer`. If the supplied file has no matching client, add this package to the Firebase project and download a regenerated config. The Android Google Services plugin reads the ignored private copy at `android/app/google-services.json` during the build.
2. Keep the Firebase Admin service account as the ignored root file `firebase-adminsdk.json`. Compose mounts it read-only at `/run/secrets/firebase-adminsdk.json` and sets `FIREBASE_CREDENTIALS_PATH` for the backend. A missing/invalid file disables push without blocking API startup.
3. Start or rebuild the backend using the normal MongoDB Compose workflow from the root documentation. Never commit either credential file; the service-account file is a server secret.
4. Build and run the separate Android observer app:

   ```sh
   cd mobile-observer
   flutter pub get
   flutter build apk
   flutter run
   ```

5. Sign in on an Android 13+ device/emulator and allow notifications. The app registers the FCM token after login/session restore and updates registration after token rotation. Logout unregisters the current token.

The authenticated backend contract is `POST /devices/fcm-token` and `DELETE /devices/fcm-token`, both with `{ "token": "…", "platform": "android" }`. The token is bound to the current account, and re-registering it moves it to that account. Only active diagram owners/members receive activity notifications; the initiating account is excluded when known. Presence and cursor events are never sent.

Android uses native Firebase defaults from Google Services configuration. iOS remains gracefully unavailable until a separate `GoogleService-Info.plist`, APNs setup, and Firebase iOS app configuration are supplied. No fake Firebase options are included. The observer remains read-only: token registration is its only additional authenticated write; it never edits diagrams, sends chat, invokes AI, or changes seen markers.

To verify delivery, use an Android device/emulator with network access and notification permission, perform a diagram change from another account, and tap the generic notification. Foreground messages show a generic notice; background and terminated taps open the referenced diagram. Backend tests exercise recipient filtering, event allowlisting, payload privacy, FCM batch sizing, invalid-token cleanup, and disabled mode.

## Checks

```sh
flutter analyze
flutter test
```

The test suite covers tolerant JSON parsing, URL normalization, authenticated token registration/removal, auth expiry, receive-only WebSocket reconnect/1008 handling, and the absence of edit/chat-send controls.
