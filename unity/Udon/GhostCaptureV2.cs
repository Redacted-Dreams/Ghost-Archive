using UdonSharp;
using UnityEngine;
using VRC.SDKBase;
using VRC.Udon;

/// <summary>
/// V2: no opt-out (handled by a separate system); does nothing except on the scribe account's client.
/// Put this on a GameObject with a trigger collider covering the capture area.
/// Each player who enters gets a random capture time inside [minDelay, maxDelay].
/// If they are still inside when it fires their pose is logged.
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class GhostCaptureV2 : UdonSharpBehaviour
{
    [Header("Scribe")]
    [Tooltip("Display name of the account whose log the scribe reads. Empty = capture disabled.")]
    public string scribeDisplayName = "";

    [Header("Timing")]
    [Tooltip("Seconds after entering before a capture can fire")]
    public float minDelay = 20f;
    [Tooltip("Latest a capture can fire after entering")]
    public float maxDelay = 180f;
    [Tooltip("Ignore players who leave before this many seconds")]
    public float minDwell = 10f;

    [Header("Sanity")]
    public float minHeight = 0.3f;
    public float maxHeight = 6.0f;
    [Tooltip("Reject captures while the player is airborne")]
    public bool requireGrounded = true;

    [Header("Optional local cue")]
    [Tooltip("UdonBehaviour to send 'OnGhostCaptured' to when the LOCAL player is captured")]
    public UdonBehaviour localCueTarget;

    private const int MAX_TRACKED = 80;
    private const int BONE_COUNT = 19;

    // Parallel arrays, Udon has no List<>
    private int[] _ids = new int[MAX_TRACKED];
    private float[] _enterTime = new float[MAX_TRACKED];
    private float[] _fireTime = new float[MAX_TRACKED];
    private bool[] _done = new bool[MAX_TRACKED];
    private int _count = 0;

    private HumanBodyBones[] _bones;
    private bool _isScribe = false;

    void Start()
    {
        VRCPlayerApi local = Networking.LocalPlayer;
        _isScribe = local != null && scribeDisplayName.Length > 0 && local.displayName.Equals(scribeDisplayName);
        if (scribeDisplayName.Length == 0) Debug.LogWarning("[GhostCaptureV2] scribeDisplayName is empty; capture disabled");

        _bones = new HumanBodyBones[BONE_COUNT];
        _bones[0] = HumanBodyBones.Hips;
        _bones[1] = HumanBodyBones.Spine;
        _bones[2] = HumanBodyBones.Chest;
        _bones[3] = HumanBodyBones.Neck;
        _bones[4] = HumanBodyBones.Head;
        _bones[5] = HumanBodyBones.LeftShoulder;
        _bones[6] = HumanBodyBones.LeftUpperArm;
        _bones[7] = HumanBodyBones.LeftLowerArm;
        _bones[8] = HumanBodyBones.LeftHand;
        _bones[9] = HumanBodyBones.RightShoulder;
        _bones[10] = HumanBodyBones.RightUpperArm;
        _bones[11] = HumanBodyBones.RightLowerArm;
        _bones[12] = HumanBodyBones.RightHand;
        _bones[13] = HumanBodyBones.LeftUpperLeg;
        _bones[14] = HumanBodyBones.LeftLowerLeg;
        _bones[15] = HumanBodyBones.LeftFoot;
        _bones[16] = HumanBodyBones.RightUpperLeg;
        _bones[17] = HumanBodyBones.RightLowerLeg;
        _bones[18] = HumanBodyBones.RightFoot;
    }

    // ---------- tracking ----------

    public override void OnPlayerTriggerEnter(VRCPlayerApi player)
    {
        if (!_isScribe) return;
        if (player == null || !player.IsValid()) return;
        if (Find(player.playerId) >= 0) return;
        if (_count >= MAX_TRACKED) return;

        _ids[_count] = player.playerId;
        _enterTime[_count] = Time.time;
        _fireTime[_count] = Time.time + Random.Range(minDelay, maxDelay);
        _done[_count] = false;
        _count++;
    }

    public override void OnPlayerTriggerExit(VRCPlayerApi player)
    {
        if (player == null) return;
        Remove(Find(player.playerId));
    }

    public override void OnPlayerLeft(VRCPlayerApi player)
    {
        if (player == null) return;
        Remove(Find(player.playerId));
    }

    void Update()
    {
        float now = Time.time;
        for (int i = 0; i < _count; i++)
        {
            if (_done[i] || now < _fireTime[i]) continue;
            _done[i] = true; // one shot per visit regardless of outcome

            VRCPlayerApi p = VRCPlayerApi.GetPlayerById(_ids[i]);
            if (p == null || !p.IsValid()) continue;
            if (now - _enterTime[i] < minDwell) continue;

            TryCapture(p);
        }
    }

    private int Find(int id)
    {
        for (int i = 0; i < _count; i++) if (_ids[i] == id) return i;
        return -1;
    }

    private void Remove(int idx)
    {
        if (idx < 0) return;
        int last = _count - 1;
        _ids[idx] = _ids[last];
        _enterTime[idx] = _enterTime[last];
        _fireTime[idx] = _fireTime[last];
        _done[idx] = _done[last];
        _count--;
    }

    // ---------- capture ----------

    private void TryCapture(VRCPlayerApi p)
    {
        if (requireGrounded && !p.IsPlayerGrounded()) return;

        float height = p.GetAvatarEyeHeightAsMeters();
        if (height < minHeight || height > maxHeight) return;

        Vector3 hips = p.GetBonePosition(HumanBodyBones.Hips);
        Vector3 head = p.GetBonePosition(HumanBodyBones.Head);
        if (hips == Vector3.zero || head == Vector3.zero) return; // unrigged / non-humanoid

        // Root = hips in world space
        string body = SanitizeName(p.displayName)
            + "|" + UnixNow()
            + "|" + Mathf.RoundToInt(height * 1000f)
            + "|" + Mm(hips.x) + "," + Mm(hips.y) + "," + Mm(hips.z)
            + "|";

        for (int b = 0; b < BONE_COUNT; b++)
        {
            Vector3 w = p.GetBonePosition(_bones[b]);
            Vector3 r = (w == Vector3.zero) ? Vector3.zero : (w - hips);
            if (b > 0) body += ";";
            body += Mm(r.x) + "," + Mm(r.y) + "," + Mm(r.z);
        }

        Debug.Log("[GHOST1]|" + body + "|" + Crc(body));

        if (p.isLocal && localCueTarget != null)
            localCueTarget.SendCustomEvent("OnGhostCaptured");
    }

    // ---------- helpers ----------

    private static int Mm(float m) { return Mathf.RoundToInt(m * 1000f); }

    public static string SanitizeName(string n)
    {
        if (n == null) return "";
        return n.Replace("|", "_").Replace("\t", " ").Replace("\n", " ");
    }

    public static long UnixNow()
    {
        System.DateTime epoch = new System.DateTime(1970, 1, 1, 0, 0, 0, System.DateTimeKind.Utc);
        return (long)(System.DateTime.UtcNow - epoch).TotalSeconds;
    }

    public static int Crc(string s)
    {
        int sum = 0;
        for (int i = 0; i < s.Length; i++) sum = (sum + s[i]) & 0xFFFF;
        return sum;
    }
}
