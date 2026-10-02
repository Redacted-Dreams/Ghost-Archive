using UdonSharp;
using UnityEngine;
using VRC.SDKBase;
using VRC.SDK3.Persistence;

/// <summary>
/// Opt-out toggle. Put on an interactable (button, lever, tablet).
/// Persists via PlayerData so it holds across devices and instances.
/// Opting out logs a tombstone so the scribe deletes any existing ghost.
/// Wire 'Toggle' to the UI Button or use Interact.
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class GhostOptOut : UdonSharpBehaviour
{
    [Header("Optional visual state")]
    public GameObject onWhenRemembered;   // shown while capture is allowed
    public GameObject onWhenForgotten;    // shown while opted out

    private bool _optedOut = false;
    private bool _restored = false;

    public override void OnPlayerRestored(VRCPlayerApi player)
    {
        if (!player.isLocal) return;
        bool v;
        _optedOut = PlayerData.TryGetBool(player, GhostCapture.OPT_OUT_KEY, out v) && v;
        _restored = true;
        Refresh();
    }

    public override void Interact() { Toggle(); }

    public void Toggle()
    {
        if (!_restored) return; // don't act before persistence has loaded
        SetOptOut(!_optedOut);
    }

    public void SetOptOut(bool value)
    {
        _optedOut = value;
        PlayerData.SetBool(GhostCapture.OPT_OUT_KEY, value);

        if (value)
        {
            string body = GhostCapture.SanitizeName(Networking.LocalPlayer.displayName)
                        + "|" + GhostCapture.UnixNow();
            Debug.Log("[GHOSTX]|" + body + "|" + GhostCapture.Crc(body));
        }
        Refresh();
    }

    private void Refresh()
    {
        if (onWhenRemembered != null) onWhenRemembered.SetActive(!_optedOut);
        if (onWhenForgotten != null) onWhenForgotten.SetActive(_optedOut);
    }
}
