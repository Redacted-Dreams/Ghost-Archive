using UdonSharp;
using UnityEngine;
using VRC.SDKBase;
using VRC.SDK3.Components;
using VRC.SDK3.Image;
using VRC.SDK3.StringLoading;
using VRC.Udon.Common.Interfaces;

/// <summary>
/// Downloads poses.png and ghosts.tsv from a trusted (github.io) URL and drives the ghost material.
/// Keeps the last good state on any failure. Refreshes on a timer.
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class GhostLoader : UdonSharpBehaviour
{
    [Header("Source (github.io is a trusted domain)")]
    public VRCUrl posesUrl;   // https://<user>.github.io/<repo>/poses.png
    public VRCUrl tsvUrl;     // https://<user>.github.io/<repo>/ghosts.tsv
    public float refreshSeconds = 120f;

    [Header("Target")]
    public MeshRenderer ghostRenderer;
    [Tooltip("Ghost copies baked into the combined mesh; archive rows beyond this are not rendered")]
    public int maxRendered = 500;

    [Header("Fallback baked into the world")]
    public Texture2D fallbackPoses;
    public TextAsset fallbackTsv;

    // Parsed metadata (parallel arrays) for later proximity labels
    [HideInInspector] public string[] names = new string[0];
    [HideInInspector] public int[] captureDay = new int[0];
    [HideInInspector] public int[] lastSeenDay = new int[0];
    [HideInInspector] public int[] visits = new int[0];
    [HideInInspector] public int ghostCount = 0;

    private VRCImageDownloader _img;
    private Material _mat;
    private bool _haveTexture = false;

    void Start()
    {
        _mat = ghostRenderer.material;
        _img = new VRCImageDownloader();

        if (fallbackPoses != null) ApplyTexture(fallbackPoses);
        if (fallbackTsv != null) ParseTsv(fallbackTsv.text);
        PushUniforms();

        Fetch();
    }

    public void Fetch()
    {
        var info = new TextureInfo();
        info.GenerateMipMaps = false;
        info.FilterMode = FilterMode.Point;
        info.WrapModeU = TextureWrapMode.Clamp;
        info.WrapModeV = TextureWrapMode.Clamp;
        info.AnisoLevel = 0;
        _img.DownloadImage(posesUrl, null, (IUdonEventReceiver)this, info);
        VRCStringDownloader.LoadUrl(tsvUrl, (IUdonEventReceiver)this);

        SendCustomEventDelayedSeconds(nameof(Fetch), refreshSeconds);
    }

    // ---------- callbacks ----------

    public override void OnImageLoadSuccess(IVRCImageDownload result)
    {
        Texture2D t = result.Result;
        if (t == null || t.width != 64) { Debug.LogWarning("[GhostLoader] bad poses.png"); return; }
        ApplyTexture(t);
        PushUniforms();
    }

    public override void OnImageLoadError(IVRCImageDownload result)
    {
        Debug.LogWarning("[GhostLoader] image error " + result.Error + " " + result.ErrorMessage);
    }

    public override void OnStringLoadSuccess(IVRCStringDownload result)
    {
        ParseTsv(result.Result);
        PushUniforms();
    }

    public override void OnStringLoadError(IVRCStringDownload result)
    {
        Debug.LogWarning("[GhostLoader] tsv error " + result.ErrorCode + " " + result.Error);
    }

    // ---------- apply ----------

    private void ApplyTexture(Texture2D t)
    {
        _mat.SetTexture("_PoseTex", t);
        _mat.SetFloat("_PoseRows", t.height);
        _haveTexture = true;
    }

    private void PushUniforms()
    {
        _mat.SetFloat("_GhostCount", Mathf.Min(ghostCount, maxRendered));
        _mat.SetFloat("_TodayDay", DaysSince2020());
        ghostRenderer.enabled = _haveTexture && ghostCount > 0;
    }

    /// Simple TSV parse. Small files only; for thousands of rows spread this across frames.
    private void ParseTsv(string text)
    {
        if (text == null) return;
        string[] lines = text.Split('\n');
        int n = 0;
        for (int i = 2; i < lines.Length; i++) if (lines[i].Trim().Length > 0) n++;

        string[] nm = new string[n];
        int[] cd = new int[n], ls = new int[n], vs = new int[n];
        int k = 0;
        for (int i = 2; i < lines.Length; i++)
        {
            string line = lines[i].Trim();
            if (line.Length == 0) continue;
            string[] f = line.Split('\t');
            if (f.Length < 5) continue;
            nm[k] = f[0];
            cd[k] = ToInt(f[1]);
            ls[k] = ToInt(f[2]);
            vs[k] = ToInt(f[3]);
            // f[4] is the row; rows are written in order so index == row
            k++;
        }
        names = nm; captureDay = cd; lastSeenDay = ls; visits = vs; ghostCount = k;
    }

    private static int ToInt(string s)
    {
        int v; return int.TryParse(s, out v) ? v : 0;
    }

    public static int DaysSince2020()
    {
        System.DateTime e = new System.DateTime(2020, 1, 1, 0, 0, 0, System.DateTimeKind.Utc);
        return (int)(System.DateTime.UtcNow - e).TotalDays;
    }
}
