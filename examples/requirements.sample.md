# Sample game requirements (fixture for testing the pipeline)

> This is an **example** document shipped with APKHarness to demo requirement parsing and
> test-case generation. Replace it with the real spec for your game. Nothing here is a
> claim about any actual product.

## 1. Core loop

- The game must show a main menu with Play, Shop and Settings buttons.
- Pressing Play must open the level selection screen.
- The player must be able to start a level from the level selection screen.
- The game must not crash during a 10 minute session.

## 2. Economy

- Collecting a coin must increase the coin balance by 10 coins.
- Upgrading a car must cost 200 coins and deduct them from the balance.
- The coin balance must persist after the game is closed and reopened.

## 3. Levels

- The next level must unlock after completing the current level.
- A failed level must offer a restart without losing earned coins.

## 4. Ads

- A rewarded video ad must be available on the revive screen.
- Watching the rewarded ad must grant exactly one revive.
- An interstitial ad must be shown after every third level completion.

## 5. In-app purchases

- The coin pack product must grant 500 coins after a successful purchase.
- Cancelling a purchase must not grant any coins.
- Restore purchases must restore the no-ads entitlement.

## 6. Non-functional

- The game should run at 60 fps on a mid-range device.
- The settings screen should be user friendly.
- The backend must log every session to the analytics dashboard.
