using UdonSharp;
using UnityEngine;
using VRC.SDKBase;
using VRC.SDK3.Components;
using VRC.SDK3.Image;
using VRC.SDK3.StringLoading;
using VRC.Udon.Common.Interfaces;

/// <summary>
/// V2: ghosts come from two sources, drawn in the same single draw call.
///   base - poses_base.png + ghosts_base.tsv baked into the world (scribe --bake), shipped on publish.
///   new  - poses.png + ghosts.tsv on GitHub Pages: only ghosts captured since the last bake.
/// Ghost index i < baseCount reads the base texture; i >= newStart reads the new texture at row i - newStart.
/// Overlap (world baked after the data repo last updated) prefers base; a gap (data repo trimmed
/// before the world was republished) is simply not drawn until the world is updated.
/// Keeps the last good download on any failure. Refreshes on a timer.
/// </summary>
[UdonBehaviourSyncMode(BehaviourSyncMode.None)]
public class GhostLoaderV2 : UdonSharpBehaviour
{
    [Header("New ghosts (github.io is a trusted domain)")]
    public VRCUrl posesUrl;   // https://<user>.github.io/<data-repo>/poses.png
    public VRCUrl tsvUrl;     // https://<user>.github.io/<data-repo>/ghosts.tsv
    public float refreshSeconds = 120f;

    [Header("Base ghosts baked into the world")]
    public Texture2D basePoses;   // poses_base.png: sRGB off, no compression, point, no mips
    public TextAsset baseTsv;     // ghosts_base.tsv (rename to .txt if Unity won't import it)

    [Header("Target")]
    public MeshRenderer ghostRenderer;
    [Tooltip("Ghost copies baked into the combined mesh; ghosts beyond this are not rendered")]
    public int maxRendered = 500;

    // Metadata indexed by ghost index (base rows then new rows), for later proximity labels
    [HideInInspector] public string[] names = new string[0];
    [HideInInspector] public int[] captureDay = new int[0];
    [HideInInspector] public int ghostCount = 0;

    private VRCImageDownloader _img;
    private Material _mat;

    private string[] _baseNames = new string[0];
    private int[] _baseDays = new int[0];
    private int _baseCount = 0;

    private string[] _newNames = new string[0];
    private int[] _newDays = new int[0];
    private int _newStart = 0;
    private int _newCount = 0;
    private bool _haveNewTexture = false;

    // ParseTsv outputs
    private string[] _pNames;
    private int[] _pDays;
    private int _pBase;

    void Start()
    {
        _mat = ghostRenderer.material;
        _img = new VRCImageDownloader();

        if (basePoses != null)
        {
            _mat.SetTexture("_PoseTex", basePoses);
            _mat.SetFloat("_PoseRows", basePoses.height);
        }
        if (baseTsv != null && ParseTsv(baseTsv.text))
        {
            _baseNames = _pNames; _baseDays = _pDays; _baseCount = _pNames.Length;
        }
        _newStart = _baseCount;
        Rebuild();

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
        if (t == null || t.width != 64) { Debug.LogWarning("[GhostLoaderV2] bad poses.png"); return; }
        _mat.SetTexture("_PoseTexNew", t);
        _mat.SetFloat("_PoseRowsNew", t.height);
        _haveNewTexture = true;
        Rebuild();
    }

    public override void OnImageLoadError(IVRCImageDownload result)
    {
        Debug.LogWarning("[GhostLoaderV2] image error " + result.Error + " " + result.ErrorMessage);
    }

    public override void OnStringLoadSuccess(IVRCStringDownload result)
    {
        if (!ParseTsv(result.Result)) { Debug.LogWarning("[GhostLoaderV2] bad ghosts.tsv"); return; }
        _newNames = _pNames; _newDays = _pDays; _newCount = _pNames.Length; _newStart = _pBase;
        Rebuild();
    }

    public override void OnStringLoadError(IVRCStringDownload result)
    {
        Debug.LogWarning("[GhostLoaderV2] tsv error " + result.ErrorCode + " " + result.Error);
    }

    // ---------- apply ----------

    /// Merges base + new metadata by ghost index and pushes uniforms.
    private void Rebuild()
    {
        // New rows only count once both the texture and the tsv describing it have arrived
        int newCount = _haveNewTexture ? _newCount : 0;
        int total = Mathf.Max(_baseCount, newCount > 0 ? _newStart + newCount : 0);

        string[] nm = new string[total];
        int[] cd = new int[total];
        for (int i = 0; i < _baseCount; i++) { nm[i] = _baseNames[i]; cd[i] = _baseDays[i]; }
        for (int j = 0; j < newCount; j++)
        {
            int i = _newStart + j;
            if (i < _baseCount) continue; // overlap: base wins
            nm[i] = _newNames[j]; cd[i] = _newDays[j];
        }
        names = nm; captureDay = cd; ghostCount = total;

        _mat.SetFloat("_BaseCount", _baseCount);
        _mat.SetFloat("_NewStart", _newStart);
        _mat.SetFloat("_GhostCount", Mathf.Min(total, maxRendered));
        _mat.SetFloat("_TodayDay", DaysSince2020());
        ghostRenderer.enabled = total > 0;
    }

    /// TSV v2: "v 2", "base N", header, then rows. Fills _pNames/_pDays/_pBase.
    /// Small files only; for thousands of rows spread this across frames.
    private bool ParseTsv(string text)
    {
        if (text == null) return false;
        string[] lines = text.Split('\n');
        int n = 0;
        bool counting = false;
        for (int i = 0; i < lines.Length; i++)
        {
            if (counting) { if (IsRow(lines[i])) n++; }
            else if (lines[i].StartsWith("name\t")) counting = true;
        }

        string[] nm = new string[n];
        int[] cd = new int[n];
        int b = 0, k = 0;
        bool inRows = false;
        for (int i = 0; i < lines.Length; i++)
        {
            string line = lines[i].Trim();
            if (!inRows)
            {
                // header block; checked only here so a player named "base" can't be misread
                if (line.StartsWith("base\t")) b = ToInt(line.Substring(5));
                else if (line.StartsWith("name\t")) inRows = true;
                continue;
            }
            if (!IsRow(line)) continue;
            string[] f = line.Split('\t');
            nm[k] = f[0];
            cd[k] = ToInt(f[1]);
            // f[4] is the absolute ghost index; rows are written in order so f[4] == base + k
            k++;
        }
        _pNames = nm; _pDays = cd; _pBase = b;
        return true;
    }

    private static bool IsRow(string line)
    {
        return line.Trim().Split('\t').Length >= 5;
    }

    private static int ToInt(string s)
    {
        int v; return int.TryParse(s.Trim(), out v) ? v : 0;
    }

    public static int DaysSince2020()
    {
        System.DateTime e = new System.DateTime(2020, 1, 1, 0, 0, 0, System.DateTimeKind.Utc);
        return (int)(System.DateTime.UtcNow - e).TotalDays;
    }
}
