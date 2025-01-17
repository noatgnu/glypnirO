from io import StringIO
from copy import deepcopy
import numpy as np
import pandas as pd
import re

from glypnirO_GUI.get_uniprot import UniprotParser
from sequal.sequence import Sequence
from sequal.resources import glycan_block_dict

sequence_column_name = "Peptide\n< ProteinMetrics Confidential >"
glycans_column_name = "Glycans\nNHFAGNa"
starting_position_column_name = "Starting\nposition"
modifications_column_name = "Modification Type(s)"
observed_mz = "Calc.\nmass (M+H)"
protein_column_name = "Protein Name"
rt = "Scan Time"
selected_aa = {"N", "S", "T"}

regex_glycan_number_pattern = "\d+"
glycan_number_regex = re.compile(regex_glycan_number_pattern)
regex_pattern = "\.[\[\]\w\.\+\-]*\."
sequence_regex = re.compile(regex_pattern)
uniprot_regex = re.compile("(?P<accession>[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2})(?P<isoform>-\d)?")
glycan_regex = re.compile("(\w+)\((\d+)\)")


def filter_U_only(df):
    unique_glycan = df["Glycans"].unique()
    if len(unique_glycan) > 1 or True not in np.isin(unique_glycan, "U"):
        # print(unique_glycan)
        return True
    return False


def filter_with_U(df):
    unique_glycan = df["Glycans"].unique()
    if len(unique_glycan) > 1 \
            and \
            True in np.isin(unique_glycan, "U"):
        return True
    return False

def get_mod_value(amino_acid):
    if amino_acid.mods:
        if amino_acid.mods[0].value.startswith("+"):
            return float(amino_acid.mods[0].value[1:])
        else:
            return -float(amino_acid.mods[0].value[1:])
    else:
        return 0


def load_fasta(fasta_file_path, selected=None, selected_prefix=""):
    with open(fasta_file_path, "rt") as fasta_file:
        result = {}
        current_seq = ""
        for line in fasta_file:
            line = line.strip()

            if line.startswith(">"):
                if selected:
                    if selected_prefix + line[1:] in selected:
                        result[line[1:]] = ""
                        current_seq = line[1:]
                else:
                    result[line[1:]] = ""
                    current_seq = line[1:]
            else:
                result[current_seq] += line
        return result


class Result:
    def __init__(self, df):
        self.df = df
        self.empty = df.empty

    def calculate_proportion(self, occupancy=True):
        df = self.df.copy()
        #print(df)
        if not occupancy:
            df = df[df["Glycans"] != "U"]
        if "Peptides" in df.columns:
            gr = [# "Isoform",
                  "Peptides", "Position"]
        else:
            gr = [# "Isoform",
                  "Position"]
        for _, g in df.groupby(gr):
            total = g["Value"].sum()
            for i, r in g.iterrows():
                df.at[i, "Value"] = r["Value"] / total

        return df

    def to_summary(self, df=None, name="", trust_byonic=False, occupancy=True):
        if df is None:
            df = self.df
        if not occupancy:
            df = df[df["Glycans"] != "U"]
        if trust_byonic:
            temp = df.set_index([# "Isoform",
                                 "Position", "Glycans"])
        else:
            temp = df.set_index([# "Isoform",
                                 "Peptides", "Glycans", "Position"])

        temp.rename(columns={"Value": name}, inplace=True)
        return temp


class GlypnirOComponent:
    def __init__(self, filename, area_filename, replicate_id, condition_id, protein_name, minimum_score=0, trust_byonic=False, legacy=False):
        if type(filename) == pd.DataFrame:
            data = filename.copy()
        else:
            data = pd.read_excel(filename, sheet_name="Spectra")
        if type(area_filename) == pd.DataFrame:
            file_with_area = area_filename
        else:
            if area_filename.endswith("xlsx"):
                file_with_area = pd.read_excel(area_filename)
            else:
                file_with_area = pd.read_csv(area_filename, sep="\t")
        data["Scan number"] = pd.to_numeric(data["Scan #"].str.extract("scan=(\d+)", expand=False))
        data = pd.merge(data, file_with_area, left_on="Scan number", right_on="First Scan")
        self.protein_name = protein_name
        self.data = data.sort_values(by=['Area'], ascending=False)
        self.replicate_id = replicate_id
        self.condition_id = condition_id
        self.data = data[data["Area"].notnull()]
        self.data = self.data[(self.data["Score"] >= minimum_score) &
                         (self.data[protein_column_name].str.contains(protein_name))
                         # (data["Protein Name"] == ">"+protein_name) &
                         ]
        self.data = self.data[~self.data[protein_column_name].str.contains(">Reverse")]
        if len(self.data.index) > 0:
            self.empty = False
        else:
            self.empty = True
        self.row_to_glycans = {}
        self.glycan_to_row = {}

        self.trust_byonic = trust_byonic
        self.legacy = legacy
        self.sequon_glycosites = set()
        self.glycosylated_seq = set()

    def calculate_glycan(self, glycan):
        current_mass = 0
        current_string = ""
        for i in glycan:
            current_string += i
            if i == ")":
                s = glycan_regex.search(current_string)
                if s:
                    name = s.group(1)
                    amount = s.group(2)
                    current_mass += glycan_block_dict[name]*int(amount)
                current_string = ""
        return current_mass

    def process(self):
        # entries_number = len(self.data.index)
        # if analysis == "N-glycan":
        #     expand_window = 2
        #     self.data["total_number_of_asn"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_n-linked_sequon"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_hexnac"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_deamidation"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_modded_asn"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_unmodded_asn"] = pd.Series([0] * entries_number, index=self.data.index, dtype=int)
        # elif analysis == "O-glycan":
        #     self.data["total_number_of_hex"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_modded_ser_thr"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["total_number_of_unmodded_ser_or_thr"] = pd.Series([0]*entries_number, index=self.data.index, dtype=int)
        #     self.data["o_glycosylation_status"] = pd.Series([False]*entries_number, index=self.data.index, dtype=bool)
        for i, r in self.data.iterrows():
            glycan_dict = {}
            search = sequence_regex.search(r[sequence_column_name])
            seq = Sequence(search.group(0))
            stripped_seq = seq.to_stripped_string()
            # modifications = {}
            # if pd.notnull(r[modifications_column_name]):
            #
            #     for mod in r[modifications_column_name].split(","):
            #         number = 1
            #         if "*" in mod:
            #             m = mod.split("*")
            #             minimod = Sequence(m[0].strip())
            #             number = int(m[1].strip())
            #
            #         else:
            #             minimod = Sequence(mod.strip())
            #         for mo in minimod[0].mods:
            #             if mo.value not in modifications:
            #                 modifications[mo.value] = {}
            #             modifications[mo.value][minimod[0].value] = {"mod": deepcopy(mo),
            #                                                                      "number": number}
            #         #if minimod[0].mods[0].value not in modifications:
            #         #    modifications[minimod[0].mods[0].value] = {}
            #         #modifications[minimod[0].mods[0].value][minimod[0].value] = {"mod": deepcopy(minimod[0].mods[0]),
            #         #                                                             "number": number}
            #
            #         if minimod[0].value == "N":
            #             if analysis == "N-glycan":
            #                 for mo in minimod[0].mods:
            #                     if mo.value == 1:
            #                         #if minimod[0].mods[0].value == 1:
            #                         self.data.at[i, "total_number_of_deamidation"] += number
            #                     self.data.at[i, "total_number_of_modded_asn"] += number
            #         elif minimod[0].value in "ST":
            #             if analysis == "O-glycan":
            #                 for mo in minimod[0].mods:
            #                     self.data.at[i, "total_number_of_modded_ser_thr"] += number
            glycans = []
            if pd.notnull(r[glycans_column_name]):
                glycans = r[glycans_column_name].split(",")
            if search:
                self.data.at[i, "stripped_seq"] = stripped_seq.rstrip(".").lstrip(".")

                origin_seq = r[starting_position_column_name] - 1
                glycan_reordered = []
                self.data.at[i, "origin_start"] = origin_seq
                self.data.at[i, "Ending Position"] = r[starting_position_column_name] + len(self.data.at[i, "stripped_seq"])
                self.data.at[i, "position_to_glycan"] = ""
                if self.trust_byonic:
                    n_site_status = {}
                    p_n = r[protein_column_name].lstrip(">")
                    # print(self.protein_name, p_n)

                    # motifs = [match for match in seq.find_with_regex(motif, ignore=seq.gaps())]
                    # if self.analysis == "N-glycan":
                    #     if len(fasta_library[p_n]) >= origin_seq + expand_window:
                    #         if expand_window:
                    #             expanded_window = Sequence(fasta_library[p_n][origin_seq: origin_seq + len(self.data.at[i, "stripped_seq"]) + expand_window])
                    #             expanded_window_motifs = [match for match in expanded_window.find_with_regex(motif, ignore=expanded_window.gaps())]
                    #             origin_map = [i.start + origin_seq for i in expanded_window_motifs]
                    #             if len(expanded_window_motifs) > len(motifs):
                    #                 self.data.at[i, "expanded_motif"] = str(expanded_window[expanded_window_motifs[-1]])
                    #             self.data.at[i, "expanded_aa"] = str(expanded_window[-expand_window:])
                    #
                    #     else:
                    #         origin_map = [i.start + origin_seq for i in motifs]
                    # else:
                    #     origin_map = [i.start + origin_seq for i in motifs]
                    #
                    # if analysis == "N-glycan":
                    #     self.data.at[i, "total_number_of_asn"] = seq.count("N", 0, len(seq))
                    #     if expand_window:
                    #         self.data.at[i, "total_number_of_n-linked_sequon"] = len(expanded_window_motifs)
                    #     else:
                    #         self.data.at[i, "total_number_of_n-linked_sequon"] = len(motifs)
                    #     self.data.at[i, "total_number_of_unmodded_asn"] = self.data.at[i, "total_number_of_asn"] - self.data.at[i, "total_number_of_modded_asn"]
                    # elif analysis == "O-glycan":
                    #     self.data.at[i, "total_number_of_ser_thr"] = seq.count("S", 0, len(seq)) + seq.count("T", 0, len(seq))
                    #     self.data.at[i, "total_number_of_unmodded_ser_or_thr"] = self.data.at[i, "total_number_of_modded_ser_thr"] - self.data.at[i, "total_number_of_modded_ser_thr"]

                    # current_glycan = 0
                    max_glycans = len(glycans)
                    glycosylation_count = 1

                    if max_glycans:
                        self.row_to_glycans[i] = np.sort(glycans)
                        for g in glycans:
                            data_gly = self.calculate_glycan(g)
                            glycan_dict[str(round(data_gly, 3))] = g
                            self.glycan_to_row[g] = i

                    glycosylated_site = []
                    for aa in range(1, len(seq) - 1):
                        if seq[aa].mods:
                            mod_value = float(seq[aa].mods[0].value)
                            round_mod_value = round(mod_value)
                            # str_mod_value = seq[aa].mods[0].value[0] + str(round_mod_value)
                            #if str_mod_value in modifications:
                                # if seq[aa].value in "ST" and analysis == "O-glycan":
                                #     if round_mod_value == 80:
                                #         continue

                                # if seq[aa].value in modifications[str_mod_value]:
                                    # if seq[aa].value == "N" and round_mod_value == 1:
                                    #     seq[aa].extra = "Deamidated"
                                    #     continue

                                    # if modifications[str_mod_value][seq[aa].value]['number'] > 0:
                                    #     modifications[str_mod_value][seq[aa].value]['number'] -= 1
                                    #     seq[aa].mods[0].mass = mod_value
                            round_3 = round(mod_value, 3)
                            if str(round_3) in glycan_dict:
                                seq[aa].extra = "Glycosylated"
                                pos = int(r[starting_position_column_name]) + aa - 2
                                self.sequon_glycosites.add(pos + 1)
                                position = "{}_position".format(str(glycosylation_count))
                                self.data.at[i, position] = seq[aa].value + str(pos + 1)
                                glycosylated_site.append(self.data.at[i, position] + "_" + str(round_mod_value))
                                glycosylation_count += 1
                                glycan_reordered.append(glycan_dict[str(round_3)])
                    if glycan_reordered:
                        self.data.at[i, "position_to_glycan"] = ",".join(glycan_reordered)
                    self.data.at[i, "glycoprofile"] = ";".join(glycosylated_site)

                                # if seq[aa].value == "N":
                                #     if analysis == "N-glycan":
                                #         if self.trust_byonic:
                                #             if  not in origin_map:
                                #
                                #             # position = "{}_position".format(str(glycosylation_count))
                                #             # self.data.at[i, position] = seq[aa].value + str(
                                #             #     r[starting_position_column_name]+aa)
                                #             # self.data.at[i, position + "_match"] = "H"
                                #             # glycosylation_count += 1
                                #         self.data.at[i, "total_number_of_hexnac"] += 1
                                # elif seq[aa].value in "ST":
                                #     if analysis == "O-glycan":
                                #         self.data.at[i, "total_number_of_hex"] += 1


                            # if mod_value in modifications:
                            #     if seq[aa].value in "ST" and analysis == "O-glycan":
                            #         if round_mod_value == 80:
                            #             continue
                            #
                            #     if seq[aa].value in modifications[mod_value]:
                            #         if seq[aa].value == "N" and round_mod_value == 1:
                            #             seq[aa].extra = "Deamidated"
                            #             continue
                            #         if modifications[mod_value][seq[aa].value]['number'] > 0:
                            #             modifications[mod_value][seq[aa].value]['number'] -= 1
                            #             seq[aa].mods[0].mass = float(seq[aa].mods[0].value)
                            #
                            #             if max_glycans and current_glycan != max_glycans:
                            #
                            #                 seq[aa].mods[0].value = glycans[current_glycan]
                            #                 seq[aa].extra = "Glycosylated"
                            #
                            #                 if seq[aa].value == "N":
                            #                     if analysis == "N-glycan":
                            #                         if "hexnac" in glycans[current_glycan].lower():
                            #                             self.data.at[i, "total_number_of_hexnac"] += 1
                            #
                            #                 elif seq[aa].value in "ST":
                            #                     if analysis == "O-glycan":
                            #                         self.data.at[i, "total_number_of_hex"] += 1
                            #
                            #                 current_glycan += 1
                                            #if current_glycan == max_glycans:
                                                #break

                    # for n in origin_map:
                    #     position = "{}_position".format(str(glycosylation_count))
                    #     self.data.at[i, position] = seq[n-origin_seq+1].value + str(
                    #         n + 1)
                    #
                    #     if seq[n-origin_seq+1].extra == "Glycosylated":
                    #         self.data.at[i, position + "_match"] = "H"
                    #     elif seq[n-origin_seq+1].extra == "Deamidated":
                    #         self.data.at[i, position + "_match"] = "D"
                    #     else:
                    #         self.data.at[i, position + "_match"] = "U"
                    #
                    #     if analysis == "N-glycan":
                    #         if self.legacy:
                    #             if self.data.at[i, "total_number_of_n-linked_sequon"] != self.data.at[i, "total_number_of_hexnac"]:
                    #                 if seq[n-origin_seq+1].extra == "Deamidated":
                    #                     if self.data.at[i, "total_number_of_hexnac"] > 0:
                    #                         self.data.at[i, position + "_match"] = "D/H"
                    #                         if self.data.at[i, "total_number_of_unmodded_asn"] > 0:
                    #                             self.data.at[i, position + "_match"] = "D/H/U"
                    #                     else:
                    #                         self.data.at[i, position + "_match"] = "D"
                    #                 else:
                    #                     if self.data.at[i, "total_number_of_hexnac"] > 0:
                    #                         if self.data.at[i, "total_number_of_deamidation"] == 0:
                    #                             self.data.at[i, position + "_match"] = "H"
                    #                         else:
                    #                             self.data.at[i, position + "_match"] ="D/H"
                    #                         if self.data.at[i, "total_number_of_unmodded_asn"] > 0:
                    #                             self.data.at[i, position + "_match"] = "D/H/U"
                    #                 if not seq[n-origin_seq+1].extra:
                    #                     if self.data.at[i, "total_number_of_hexnac"] > 0 and self.data.at[i, "total_number_of_deamidation"]> 0:
                    #                         self.data.at[i, position + "_match"] = "D/H"
                    #                         if self.data.at[i, "total_number_of_unmodded_asn"] > 0:
                    #                             self.data.at[i, position + "_match"] = "D/H/U"
                    #                     elif self.data.at[i, "total_number_of_hexnac"] > 0:
                    #                         self.data.at[i, position + "_match"] = "H"
                    #                         if self.data.at[i, "total_number_of_unmodded_asn"] > 0:
                    #                             self.data.at[i, position + "_match"] = "D/H/U"
                    #                     else:
                    #                         self.data.at[i, position + "_match"] = "U"
                    #     glycosylation_count += 1
                else:
                    if pd.notnull(r[glycans_column_name]):
                        glycans = r[glycans_column_name].split(",")
                        glycans.sort()
                        self.data.at[i, glycans_column_name] = ",".join(glycans)
                        self.data.at[i, "glycosylation_status"] = True
                        self.glycosylated_seq.add(self.data.at[i, "stripped_seq"])

    def analyze(self, max_sites=0, combine_d_u=True, splitting_sites=False):
        result = []
        temp = self.data.sort_values(["Area", "Score"], ascending=False)
        temp[glycans_column_name] = temp[glycans_column_name].fillna("None")
        out = []

        if self.trust_byonic:
            seq_glycosites = list(self.sequon_glycosites)
            seq_glycosites.sort()
            # print(seq_glycosites)
            # if self.analysis == "N-glycan":
                # if max_sites == 0:
                #     temp = temp[(0 < temp["total_number_of_n-linked_sequon"])]
                # else:
                #     temp = temp[(0 < temp["total_number_of_n-linked_sequon"]) & (temp["total_number_of_n-linked_sequon"]<= max_sites) ]
            for i, g in temp.groupby(["stripped_seq", "z", "glycoprofile", observed_mz]):
                seq_within = []
                unique_row = g.loc[g["Area"].idxmax()]
                #
                # glycan = 0
                # first_site = ""
                if seq_glycosites:
                    for n in seq_glycosites:
                        if unique_row[starting_position_column_name] <= n < unique_row["Ending Position"]:
                            # print(unique_row["stripped_seq"], n, unique_row[starting_position_column_name])
                            seq_within.append(
                                unique_row["stripped_seq"][n-unique_row[starting_position_column_name]]+str(n))
                # print(unique_row)
                # if self.legacy:
                #     for c in range(len(unique_row.index)):
                #         if unique_row.index[c].endswith("_position"):
                #
                #             if pd.notnull(unique_row[unique_row.index[c]]):
                #                 if not first_site:
                #                     first_site = unique_row[unique_row.index[c]]
                #                 if unique_row[unique_row.index[c]] not in result:
                #                     result[unique_row[unique_row.index[c]]] = {}
                #
                #                 if "U" in unique_row[unique_row.index[c+1]]:
                #                     if "U" not in result[unique_row[unique_row.index[c]]]:
                #                         result[unique_row[unique_row.index[c]]]["U"] = 0
                #                     result[unique_row[unique_row.index[c]]]["U"] += unique_row["Area"]
                #                 elif "D" in unique_row[unique_row.index[c+1]]:
                #                     if combine_d_u:
                #                         if "U" not in result[unique_row[unique_row.index[c]]]:
                #                             result[unique_row[unique_row.index[c]]]["U"] = 0
                #                         result[unique_row[unique_row.index[c]]]["U"] += unique_row["Area"]
                #                     else:
                #                         if "D" not in result[unique_row[unique_row.index[c]]]:
                #                             result[unique_row[unique_row.index[c]]]["D"] = 0
                #                         result[unique_row[unique_row.index[c]]]["D"] += unique_row["Area"]
                #                 else:
                #                     if splitting_sites or unique_row["total_number_of_hexnac"] == 1:
                #
                #                         if self.row_to_glycans[unique_row.name][glycan] not in result[unique_row[unique_row.index[c]]]:
                #                             result[unique_row[unique_row.index[c]]][self.row_to_glycans[unique_row.name][glycan]] = 0
                #                         result[unique_row[unique_row.index[c]]][
                #                             self.row_to_glycans[unique_row.name][glycan]] += unique_row["Area"]
                #                         glycan += 1
                #
                #                     else:
                #                         if unique_row["total_number_of_hexnac"] > 1 and not splitting_sites:
                #                             temporary_glycan = ";".join(self.row_to_glycans[unique_row.name][glycan])
                #
                #                             if temporary_glycan not in result[unique_row[unique_row.index[c]]]:
                #                                 result[unique_row[unique_row.index[c]]][temporary_glycan] = unique_row["Area"]
                #                         break
                # else:
                glycosylation_count = 0
                glycans = unique_row["position_to_glycan"].split(",")

                for c in range(len(unique_row.index)):
                    if unique_row.index[c].endswith("_position"):
                        if pd.notnull(unique_row[unique_row.index[c]]):
                            pos = unique_row[unique_row.index[c]]
                            result.append({"Position": pos, "Glycans": glycans[glycosylation_count], "Value": unique_row["Area"]})
                            ind = seq_within.index(pos)
                            seq_within.pop(ind)
                            glycosylation_count += 1

                if seq_within:
                    for s in seq_within:
                        result.append({"Position": s, "Glycans": "U", "Value": unique_row["Area"]})
                # if N_combo:
                #
                #     N_combo.sort()
                #     sequons = ";".join(N_combo)
                #
                #     # working_isoform = unique_row["isoform"]
                #     # if working_isoform not in result:
                #     #     # if working_isoform != 1.0 and 1.0 in result:
                #     #     #     if sequons in result[working_isoform][1.0]:
                #     #     #         if unique_row[glycans_column_name] in result[working_isoform][1.0][sequons] or "U" in result[working_isoform][1.0][sequons]:
                #     #     #             working_isoform = 1.0
                #     #     # else:
                #     #     result[working_isoform] = {}
                #     if sequons not in result[working_isoform]:
                #         result[working_isoform][sequons] = {}
                #     #if pd.notnull(unique_row[glycans_column_name]):
                #     if unique_row[glycans_column_name] != "None":
                #         if unique_row[glycans_column_name] not in result[working_isoform][sequons]:
                #             result[working_isoform][sequons][unique_row[glycans_column_name]] = 0
                #         result[working_isoform][sequons][unique_row[glycans_column_name]] += unique_row["Area"]
                #     else:
                #         if "U" not in result[working_isoform][sequons]:
                #             result[working_isoform][sequons]["U"] = 0
                #         result[working_isoform][sequons]["U"] += unique_row["Area"]
                #         #print(result)
            if result:
                result = pd.DataFrame(result)

                group = result.groupby(["Position", "Glycans"])

                out = group.agg(np.sum).reset_index()
            else:
                out = pd.DataFrame([], columns=["Position", "Glycans", "Values"])
            # for k in result:
            #     for k2 in result[k]:
            #         for k3 in result[k][k2]:
            #             out.append({"Isoform": k, "Position": k2, "Glycans": k3, "Value": result[k][k2][k3]})
        else:
            # result_total = {}
            # if max_sites != 0:
            #     temp = temp[temp['total_number_of_hex'] <= max_sites]

            for i, g in temp.groupby(["stripped_seq", "z", glycans_column_name, starting_position_column_name, observed_mz]):
                unique_row = g.loc[g["Area"].idxmax()]
                if unique_row[glycans_column_name] != "None":
                    result.append({"Peptides": i[0], "Glycans": i[2], "Value": unique_row["Area"], "Position": i[3]})
                else:
                    result.append({"Peptides": i[0], "Glycans": "U", "Value": unique_row["Area"], "Position": i[3]})

            result = pd.DataFrame(result)
            group = result.groupby(["Peptides", "Position", "Glycans"])
            out = group.agg(np.sum).reset_index()
            #     working_isoform = unique_row["isoform"]
            #     if working_isoform not in result:
            #         # if working_isoform != 1.0 and 1.0 in result:
            #         #     if unique_row["stripped_seq"] in result[working_isoform][1.0]:
            #         #         #if i[3] in result[working_isoform][1.0][unique_row["stripped_seq"]]:
            #         #             # if unique_row[glycans_column_name] in result[working_isoform][1.0][unique_row["stripped_seq"]][i[3]] or "U" in \
            #         #             #         result[working_isoform][1.0][unique_row["stripped_seq"]][i[3]]:
            #         #         working_isoform = 1.0
            #         # else:
            #             result[working_isoform] = {}
            #
            #     if unique_row["stripped_seq"] not in result[working_isoform]:
            #         result[working_isoform][unique_row["stripped_seq"]] = {}
            #         # result_total[unique_row["isoform"]][unique_row["stripped_seq"]] = 0
            #     if i[3] not in result[working_isoform][unique_row["stripped_seq"]]:
            #         result[working_isoform][unique_row["stripped_seq"]][i[3]] = {}
            #     if i[2] == "None":
            #         if "U" not in result[working_isoform][unique_row["stripped_seq"]][i[3]]:
            #             result[working_isoform][unique_row["stripped_seq"]][i[3]]["U"] = 0
            #         result[working_isoform][unique_row["stripped_seq"]][i[3]]["U"] += unique_row["Area"]
            #
            #     else:
            #         # if splitting_sites:
            #         #     for gly in self.row_to_glycans[unique_row.name]:
            #         #         if gly not in result[working_isoform][unique_row["stripped_seq"]][i[3]]:
            #         #             result[working_isoform][unique_row["stripped_seq"]][i[3]][gly] = 0
            #         #         result[working_isoform][unique_row["stripped_seq"]][i[3]][gly] += unique_row["Area"]
            #         # else:
            #         if unique_row[glycans_column_name] not in result[working_isoform][unique_row["stripped_seq"]][i[3]]:
            #             result[working_isoform][unique_row["stripped_seq"]][i[3]][unique_row[glycans_column_name]] = 0
            #         result[working_isoform][unique_row["stripped_seq"]][i[3]][unique_row[glycans_column_name]] += unique_row["Area"]
            #
            # for k in result:
            #     for k2 in result[k]:
            #         for k3 in result[k][k2]:
            #             for k4 in result[k][k2][k3]:
            #                 out.append({"Isoform": k, "Peptides": k2, "Glycans": k4, "Value": result[k][k2][k3][k4], "Position": k3})

        return Result(out)


class GlypnirO:
    def __init__(self, trust_byonic=False, get_uniprot=False):
        self.trust_byonic = trust_byonic
        self.components = None
        self.uniprot_parsed_data = pd.DataFrame([])
        self.get_uniprot = get_uniprot

    def add_component(self, filename, area_filename, replicate_id, sample_id):
        component = GlypnirOComponent(filename, area_filename, replicate_id, sample_id)

    def add_batch_component(self, component_list, minimum_score, protein=None, combine_uniprot_isoform=True, legacy=False):
        self.load_dataframe(component_list)
        protein_list = []
        if protein is not None:
            self.components["Protein"] = pd.Series([protein]*len(self.components.index), index=self.components.index)
            for i, r in self.components.iterrows():
                comp = GlypnirOComponent(r["filename"], r["area_filename"], r["replicate_id"], condition_id=r["condition_id"], protein_name=protein, minimum_score=minimum_score, trust_byonic=self.trust_byonic, legacy=legacy)
                self.components.at[i, "component"] = comp
                print("{} - {}, {} peptides has been successfully loaded".format(r["condition_id"], r["replicate_id"], str(len(comp.data.index))))

        else:
            components = []
            for i, r in self.components.iterrows():
                data = pd.read_excel(r["filename"], sheet_name="Spectra")
                protein_id_column = protein_column_name
                if combine_uniprot_isoform:
                    protein_id_column = "master_id"
                    for i2, r2 in data.iterrows():
                        search = uniprot_regex.search(r2[protein_column_name])
                        if not r2[protein_column_name].startswith(">Reverse") and not r2[protein_column_name].endswith("(Common contaminant protein)"):
                            if search:
                                data.at[i2, "master_id"] = search.groupdict(default="")["accession"]
                                if not self.get_uniprot:
                                    protein_list.append([search.groupdict(default="")["accession"], r2[protein_column_name]])
                                if search.groupdict(default="")["isoform"] != "":
                                    data.at[i2, "isoform"] = int(search.groupdict(default="")["isoform"][1:])
                                else:
                                    data.at[i2, "isoform"] = 1

                            else:
                                data.at[i2, "master_id"] = r2[protein_column_name]
                                data.at[i2, "isoform"] = 1
                        else:
                            data.at[i2, "master_id"] = r2[protein_column_name]
                            data.at[i2, "isoform"] = 1

                if r["area_filename"].endswith("xlsx"):
                    file_with_area = pd.read_excel(r["area_filename"])
                else:
                    file_with_area = pd.read_csv(r["area_filename"], sep="\t")

                for index, g in data.groupby([protein_id_column]):

                    u = index
                    if not u.startswith(">Reverse") and not u.endswith("(Common contaminant protein)"):
                        comp = GlypnirOComponent(g, file_with_area, r["replicate_id"],
                                                 condition_id=r["condition_id"], protein_name=u,
                                                 minimum_score=minimum_score, trust_byonic=self.trust_byonic, legacy=legacy)
                        if not comp.empty:
                            components.append({"filename": r["filename"], "area_filename": r["area_filename"], "condition_id": r["condition_id"], "replicate_id": r["replicate_id"], "Protein": u, "component": comp})
                yield i, r
                print(
                    "{} - {} peptides has been successfully loaded".format(r["condition_id"],
                                                                                      r["replicate_id"]))
            self.components = pd.DataFrame(components, columns=list(self.components.columns) + ["component", "Protein"])
            if not self.get_uniprot:
                protein_df = pd.DataFrame(protein_list, columns=["Entry", "Protein names"])
                self.uniprot_parsed_data = protein_df
                #print(self.uniprot_parsed_data)

    def load_dataframe(self, component_list):
        if type(component_list) == list:
            self.components = pd.DataFrame(component_list)
        elif type(component_list) == pd.DataFrame:
            self.components = component_list
        elif type(component_list) == str:
            if component_list.endswith(".txt"):
                self.components = pd.read_csv(component_list, sep="\t")
            elif component_list.endswith(".csv"):
                self.components = pd.read_csv(component_list)
            elif component_list.endswith(".xlsx"):
                self.components = pd.read_excel(component_list)
            else:
                raise ValueError("Input have to be list, pandas dataframe, or csv, xlsx, or tabulated txt filepath.")
        else:
            raise ValueError("Input have to be list, pandas dataframe, or csv, xlsx, or tabulated txt filepath.")

    def process_components(self):
        for i, r in self.components.iterrows():
            # print("Processing {} - {} {} for {}".format(r["condition_id"], r["replicate_id"], r["Protein"], analysis))
            r["component"].process()

    def analyze_components(self):
        # template = self.components[["Protein", "condition_id", "replicate_id"]].sort_values(["Protein", "condition_id", "replicate_id"])
        # template["label"] = pd.Series(["Raw"]*len(template.index), index=template.index)
        # template_proportion = template.copy()
        # template_proportion["label"] = pd.Series(["Proportion"]*len(template_proportion.index), index=template_proportion.index)
        #
        # index = pd.MultiIndex.from_frame(pd.concat([template, template_proportion], ignore_index=True)[["Protein", "label", "condition_id", "replicate_id"]])
        result = []
        result_without_u = []
        result_occupancy_no_calculation_u = []
        for i, r in self.components.iterrows():
            print("Analyzing", r["Protein"], r["condition_id"], r["replicate_id"], r["component"].protein_name)
            analysis_result = r["component"].analyze()
            if not analysis_result.empty:

                a = analysis_result.to_summary(name="Raw", trust_byonic=self.trust_byonic)
                pro = analysis_result.calculate_proportion()
                b = analysis_result.to_summary(pro, "Proportion", trust_byonic=self.trust_byonic)
                temp_df = self._summary(a, r, b)
                result.append(temp_df)

                a_without_u = analysis_result.to_summary(name="Raw", trust_byonic=self.trust_byonic, occupancy=False)
                pro_without_u = analysis_result.calculate_proportion(occupancy=False)
                b_without_u = analysis_result.to_summary(pro_without_u, "Proportion", trust_byonic=self.trust_byonic, occupancy=False)
                temp_df_without_u = self._summary(a_without_u, r, b_without_u)
                result_without_u.append(temp_df_without_u)

                temp_df_no_calculation_u = self._summary(a, r, b_without_u)
                result_occupancy_no_calculation_u.append(temp_df_no_calculation_u)

        result_occupancy = self._summary_format(result)
        result_occupancy_with_u = self._summary_format(result, filter_with_U, True)
        result_glycoform = self._summary_format(result_without_u)

        tempdf_index_reset_result_occupancy_with_u = result_occupancy_with_u.reset_index()
        tempdf_index_reset_result_glycoform = result_glycoform.reset_index()
        result_occupancy_glycoform_sep = pd.concat(
            [tempdf_index_reset_result_glycoform, tempdf_index_reset_result_occupancy_with_u])

        if self.trust_byonic:
            result_occupancy_glycoform_sep = result_occupancy_glycoform_sep.set_index(["Protein", "Protein names",
                                                                                       # "Isoform",
                                                                                       "Glycosylated positions in peptide", "Glycans"])
            result_occupancy_glycoform_sep = result_occupancy_glycoform_sep.sort_index(
                level=["Protein", "Protein names",
                       # "Isoform",
                       "Glycosylated positions in peptide"])
        else:

            result_occupancy_glycoform_sep = result_occupancy_glycoform_sep.set_index(
                ["Protein", "Protein names",
                 # "Isoform",
                 "Position peptide N-terminus", "Peptides", "Glycans"])
            result_occupancy_glycoform_sep = result_occupancy_glycoform_sep.sort_index(
                level=["Protein", "Protein names",
                       # "Isoform",
                       "Position peptide N-terminus", "Peptides"])

        # result = result.stack("Protein")
        # result = result.swaplevel("Protein", "Peptides")
        # result = result.swaplevel("Glycans", "Peptides")
        print("Finished analysis.")
        return {"Glycoforms":
                    result_glycoform,
                "Occupancy":
                    result_occupancy,
                "Occupancy_With_U":
                    result_occupancy_with_u,
                "Occupancy_Without_Proportion_U":
                    result_occupancy_glycoform_sep}

    def _summary_format(self, result, filter_method=filter_U_only, select_for_u=False):
        result_data = pd.concat(result)
        result_data = result_data.reset_index(drop=True)
        accessions = result_data["Protein"].unique()

        if self.uniprot_parsed_data.empty:
            if self.get_uniprot:
                parser = UniprotParser(accessions, True)

                data = []
                for i in parser.parse("tab"):
                    frame = pd.read_csv(StringIO(i), sep="\t")
                    frame = frame.rename(columns={frame.columns[-1]: "query"})
                    data.append(frame)
                self.uniprot_parsed_data = pd.concat(data, ignore_index=True)
                #
                self.uniprot_parsed_data = self.uniprot_parsed_data[['Entry', 'Protein names']]
        else:
            self.uniprot_parsed_data = self.uniprot_parsed_data.groupby(["Entry"]).head(1).reset_index().drop(["index"], axis=1)

        result_data = result_data.merge(self.uniprot_parsed_data, left_on="Protein", right_on="Entry")
        result_data.drop("Entry", 1, inplace=True)

        if self.trust_byonic:
            groups = result_data.groupby(by=["Protein", "Protein names",
                                             # "Isoform",
                                             "Position"])
        else:
            groups = result_data.groupby(by=["Protein", "Protein names",
                                             # "Isoform",
                                             "Position", "Peptides"])
        result_data = groups.filter(filter_method)
        if select_for_u:
            result_data = result_data[result_data["Glycans"] == "U"]
        if self.trust_byonic:
            result_data = result_data.rename({"Position": "Glycosylated positions in peptide"}, axis="columns")
            result_data = result_data.set_index(
                ["Label", "condition_id", "replicate_id", "Protein", "Protein names",
                 # "Isoform",
                 "Glycosylated positions in peptide", "Glycans"])
        else:
            result_data = result_data.rename({"Position": "Position peptide N-terminus"}, axis="columns")
            result_data = result_data.set_index(
                ["Label", "condition_id", "replicate_id", "Protein", "Protein names",
                 # "Isoform",
                 "Position peptide N-terminus", "Peptides", "Glycans"])
        result_data = result_data.unstack(["Label", "condition_id", "replicate_id"])
        result_data = result_data.sort_index(level=["Label", "condition_id", "replicate_id"], axis=1)
        #result_data.to_csv("test.txt", sep="\t")
        if self.trust_byonic:
            result_data = result_data.sort_index(level=["Protein", "Protein names",
                                                        # "Isoform",
                                                        "Glycosylated positions in peptide"])
        else:
            result_data = result_data.sort_index(level=["Protein", "Protein names",
                                                        # "Isoform",
                                                        "Position peptide N-terminus", "Peptides"])

        result_data.columns = result_data.columns.droplevel()
        return result_data

    def _summary(self, a, r, b):
        temp_df = pd.concat([a, b], axis=1)

        temp_df.columns.name = "Label"
        temp_df = temp_df.stack()
        lc = [temp_df]
        for c in ["Protein", "condition_id", "replicate_id"]:
            lc.append(pd.Series([r[c]] * len(temp_df.index), index=temp_df.index, name=c))
        temp_df = pd.concat(lc, axis=1)

        temp_df = temp_df.reset_index()

        return temp_df

