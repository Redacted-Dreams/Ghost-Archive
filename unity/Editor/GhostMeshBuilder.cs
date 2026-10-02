#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;

/// <summary>
/// Window: AshenChoir > Ghost Mesh Builder
/// Input: a scene instance of the low-poly rig (humanoid Animator + SkinnedMeshRenderer) in T-pose,
///        transform at identity, feet on y=0.
/// Output: a combined mesh with N ghost copies (TEXCOORD1 = bone indices, COLOR.r = weight0,
///         TEXCOORD2.x = ghost index) and a regenerated GhostRig.cginc.
/// </summary>
public class GhostMeshBuilder : EditorWindow
{
    private Animator rig;
    private SkinnedMeshRenderer smr;
    private int ghostCount = 500;
    private bool use32BitIndex = false;
    private string meshOutPath = "Assets/GhostArchive/GhostArchiveMesh.asset";
    private string cgincOutPath = "Assets/GhostArchive/Shaders/GhostRig.cginc";

    private static readonly HumanBodyBones[] BONES =
    {
        HumanBodyBones.Hips, HumanBodyBones.Spine, HumanBodyBones.Chest, HumanBodyBones.Neck, HumanBodyBones.Head,
        HumanBodyBones.LeftShoulder, HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand,
        HumanBodyBones.RightShoulder, HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand,
        HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot,
        HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot,
    };
    private static readonly int[] PARENT = { -1, 0, 1, 2, 3, 2, 5, 6, 7, 2, 9, 10, 11, 0, 13, 14, 0, 16, 17 };
    private static readonly int[] SEG_CHILD = { 1, 2, 3, 4, -1, 6, 7, 8, -1, 10, 11, 12, -1, 14, 15, -1, 17, 18, -1 };
    private static readonly string[] NAMES =
    {
        "Hips","Spine","Chest","Neck","Head","LShoulder","LUpperArm","LLowerArm","LHand",
        "RShoulder","RUpperArm","RLowerArm","RHand","LUpperLeg","LLowerLeg","LFoot","RUpperLeg","RLowerLeg","RFoot"
    };

    [MenuItem("AshenChoir/Ghost Mesh Builder")]
    static void Open() { GetWindow<GhostMeshBuilder>("Ghost Mesh Builder"); }

    void OnGUI()
    {
        rig = (Animator)EditorGUILayout.ObjectField("Rig (humanoid Animator)", rig, typeof(Animator), true);
        smr = (SkinnedMeshRenderer)EditorGUILayout.ObjectField("Skinned Mesh", smr, typeof(SkinnedMeshRenderer), true);
        ghostCount = EditorGUILayout.IntSlider("Ghost copies", ghostCount, 1, 4000);
        use32BitIndex = EditorGUILayout.Toggle("32-bit indices (PC only)", use32BitIndex);
        meshOutPath = EditorGUILayout.TextField("Mesh output", meshOutPath);
        cgincOutPath = EditorGUILayout.TextField("cginc output", cgincOutPath);

        if (smr != null)
        {
            int verts = smr.sharedMesh.vertexCount * ghostCount;
            EditorGUILayout.HelpBox($"Combined: {verts:N0} verts, {smr.sharedMesh.triangles.Length / 3 * ghostCount:N0} tris" +
                (verts > 65535 && !use32BitIndex ? "\nExceeds 16-bit index limit — lower the count or enable 32-bit." : ""),
                verts > 65535 && !use32BitIndex ? MessageType.Warning : MessageType.Info);
        }

        GUI.enabled = rig != null && smr != null;
        if (GUILayout.Button("Build")) Build();
        GUI.enabled = true;
    }

    void Build()
    {
        // --- rest bone positions relative to hips, world space (rig must be at identity)
        Transform[] boneT = new Transform[BONES.Length];
        Vector3[] rest = new Vector3[BONES.Length];
        Transform hipsT = rig.GetBoneTransform(HumanBodyBones.Hips);
        if (hipsT == null) { Debug.LogError("Rig has no Hips"); return; }
        Vector3 hips = hipsT.position;
        for (int i = 0; i < BONES.Length; i++)
        {
            boneT[i] = rig.GetBoneTransform(BONES[i]);
            if (boneT[i] == null)
            {
                // Fallback: use parent's position so the segment has zero length (shader treats as leaf-ish)
                int p = PARENT[i];
                rest[i] = p >= 0 ? rest[p] : Vector3.zero;
                Debug.LogWarning($"Rig missing {NAMES[i]}; using parent position");
            }
            else rest[i] = boneT[i].position - hips;
        }

        Transform eye = rig.GetBoneTransform(HumanBodyBones.LeftEye);
        float eyeHeight = eye != null ? eye.position.y : rig.GetBoneTransform(HumanBodyBones.Head).position.y + 0.08f;

        // --- map each skinned bone to one of our 19 (walk up parents)
        Transform[] skinBones = smr.bones;
        int[] map = new int[skinBones.Length];
        for (int i = 0; i < skinBones.Length; i++)
        {
            map[i] = 0;
            Transform t = skinBones[i];
            while (t != null)
            {
                int idx = System.Array.IndexOf(boneT, t);
                if (idx >= 0) { map[i] = idx; break; }
                t = t.parent;
            }
        }

        // --- bake rest-pose vertices into rig space (hips origin)
        Mesh baked = new Mesh();
        smr.BakeMesh(baked);
        Vector3[] bv = baked.vertices;
        Vector3[] bn = baked.normals;
        Matrix4x4 toWorld = smr.transform.localToWorldMatrix;
        Vector3 ls = smr.transform.lossyScale; // BakeMesh already applies scale
        for (int i = 0; i < bv.Length; i++)
        {
            Vector3 w = smr.transform.rotation * bv[i] + smr.transform.position; // avoid double scale
            bv[i] = w - hips;
            bn[i] = smr.transform.rotation * bn[i];
        }

        BoneWeight[] bw = smr.sharedMesh.boneWeights;
        int[] tris = smr.sharedMesh.triangles;
        int vc = bv.Length;

        // --- combine
        var verts = new List<Vector3>(vc * ghostCount);
        var norms = new List<Vector3>(vc * ghostCount);
        var uv1 = new List<Vector2>(vc * ghostCount);
        var uv2 = new List<Vector2>(vc * ghostCount);
        var cols = new List<Color>(vc * ghostCount);
        var idx = new List<int>(tris.Length * ghostCount);

        for (int g = 0; g < ghostCount; g++)
        {
            int baseV = verts.Count;
            for (int i = 0; i < vc; i++)
            {
                verts.Add(bv[i]);
                norms.Add(bn[i]);
                // Keep the two strongest influences
                BoneWeight b = bw[i];
                int i0 = map[b.boneIndex0], i1 = map[b.boneIndex1];
                float w0 = b.weight0, w1 = b.weight1;
                float sum = w0 + w1;
                if (sum <= 0) { w0 = 1; w1 = 0; sum = 1; }
                uv1.Add(new Vector2(i0, i1));
                cols.Add(new Color(w0 / sum, 0, 0, 1));
                uv2.Add(new Vector2(g, 0));
            }
            for (int t = 0; t < tris.Length; t++) idx.Add(tris[t] + baseV);
        }

        Mesh m = new Mesh { name = "GhostArchiveMesh" };
        m.indexFormat = use32BitIndex ? UnityEngine.Rendering.IndexFormat.UInt32 : UnityEngine.Rendering.IndexFormat.UInt16;
        m.SetVertices(verts);
        m.SetNormals(norms);
        m.SetUVs(1, uv1);
        m.SetUVs(2, uv2);
        m.SetColors(cols);
        m.SetTriangles(idx, 0);
        // Ghosts are placed in world space by the shader; use a huge bounds so it never culls
        m.bounds = new Bounds(Vector3.zero, Vector3.one * 2000f);

        Directory.CreateDirectory(Path.GetDirectoryName(meshOutPath));
        AssetDatabase.CreateAsset(m, meshOutPath);

        // --- cginc
        var sb = new StringBuilder();
        sb.AppendLine("// GhostRig.cginc — GENERATED by GhostMeshBuilder. Do not hand edit.");
        sb.AppendLine("#ifndef GHOST_RIG_INCLUDED");
        sb.AppendLine("#define GHOST_RIG_INCLUDED");
        sb.AppendLine($"#define GHOST_BONES {BONES.Length}");
        sb.AppendLine($"#define GHOST_RIG_EYE_HEIGHT {eyeHeight:F4}");
        sb.AppendLine($"static const float3 GHOST_REST[GHOST_BONES] = {{");
        for (int i = 0; i < BONES.Length; i++)
            sb.AppendLine($"    float3({rest[i].x:F4}, {rest[i].y:F4}, {rest[i].z:F4}){(i < BONES.Length - 1 ? "," : "")} // {i} {NAMES[i]}");
        sb.AppendLine("};");
        sb.AppendLine($"static const int GHOST_PARENT[GHOST_BONES] = {{ {string.Join(", ", PARENT)} }};");
        sb.AppendLine($"static const int GHOST_SEG_CHILD[GHOST_BONES] = {{ {string.Join(", ", SEG_CHILD)} }};");
        sb.AppendLine("#endif");
        Directory.CreateDirectory(Path.GetDirectoryName(cgincOutPath));
        File.WriteAllText(cgincOutPath, sb.ToString());

        AssetDatabase.Refresh();
        Debug.Log($"[GhostMeshBuilder] built {ghostCount} ghosts, {verts.Count:N0} verts → {meshOutPath}; rig eye height {eyeHeight:F3} m");
    }
}
#endif
