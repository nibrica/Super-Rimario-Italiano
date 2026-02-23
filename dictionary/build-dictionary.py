# Super Rimario Italiano
# Copyright (C) 2024 Nicolò Brigadoi Calamari
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.


# espeak must be installed on the system
# Glacially slow (~20 minutes)

import re
import time
from datetime import timedelta
from datetime import datetime
import csv
import subprocess

import mwxml

print("Italian dictionary builder by Nicolò Brigadoi Calamari [2024]")

# INPUT FILES
wiktionary_xml_dump_path = "input/itwiktionary-20260201-pages-articles.xml" # https://dumps.wikimedia.org/backup-index.html
colfis_frequencies_path = "input/formario_minuscolo_colfis.txt" # encoding: ISO-8859 (iso-8859-1) https://linguistica.sns.it/CoLFIS/Formario.htm
word_list_paths = [
    "input/280000_parole_italiane_napolux.txt", # https://github.com/napolux/paroleitaliane/blob/master/paroleitaliane/280000_parole_italiane.txt
    "input/parole_witalian.txt", # https://packages.debian.org/sid/witalian
    "input/dictionary_ita_pazqo.txt"# https://dumps.wikimedia.org/backup-index.html
]

#OUTPUT FILE
compiled_dictionary_path = datetime.now().strftime("parole-accenti-frequenze_%Y-%m-%d.csv")

def load_big_word_set():

    def file_to_set(file):
        result = set()
        for line in file:
            result.add(line.strip().lower())
        return result

    results = set()
    for path in word_list_paths:
        with open(path, 'r', encoding="utf-8") as f:
            print(f"Loaded '{path}'")
            results = results.union(file_to_set(f))
    print(f"Big word set created [{len(results)} words]")
    return results

# Analyze the Wiktionary XML dump to extract words and accents
def parse_wiktionary():

    def find_accent(text, word_length):
        isolated_word = re.sub(r"[;| ]+", "", text)
        if len(isolated_word) != word_length:
            return None
        accent_match = re.search(r"[àáèéìíòóùú]", isolated_word)
        return accent_match.start() if accent_match else None
    
    def parse_line(line, word_length):
        accents_found = []
        split_line = line.split("'''")
        for fragment in split_line:
            accent_match = find_accent(fragment, word_length)
            if accent_match != None:
                accents_found.append(accent_match)
        return accents_found

    def parse_sill_tag(text, word_length):
        lines = text.splitlines()
        accents_found = []
        for line in lines:
            if re.search(r"^;.*[àáèéìíòóùú]|'{3}.*[àáèéìíòóùú].*'{3}", line):
                accent_indexes = parse_line(line, word_length)
                for accent_index in accent_indexes:
                    if accent_index not in accents_found:
                        accents_found.append(accent_index)
        accent1 = None if len(accents_found) < 1 else accents_found[0]
        accent2 = None if len(accents_found) < 2 else accents_found[1]
        return accent1, accent2

    def parse_page(word, text):
        if not (word and text):
            return None
        if re.search(r"^[A-Z]|[' -]", word) or not re.search(r"{{-it-}}", text):
            return None
        word = word.lower()
        accent1, accent2 = None, None
        sill_tag = re.search(r"{{-sill-}}(.+?)(?:{|$)", text, re.DOTALL)
        if sill_tag:
            accent1, accent2 = parse_sill_tag(sill_tag.group(1), len(word))
        if word not in big_word_set and not accent1:
            return None
        return {"word": word, "accent1": accent1, "accent2": accent2}

    word_set = set()
    words_accents = []
    with open(wiktionary_xml_dump_path, "r") as f:
        print(f"Loaded '{wiktionary_xml_dump_path}'")
        dump = mwxml.Dump.from_file(f)
        for page in dump:
            for revision in page:
                current_word_accent = parse_page(page.title, revision.text)
                if current_word_accent:
                    if current_word_accent["word"] not in word_set:
                        words_accents.append(current_word_accent)
                        word_set.add(current_word_accent["word"])
                break
    print(f"Wiktionary successfully parsed [{len(word_set)} words]")
    return word_set, words_accents

# Analyze the CoLFIS frequency file to extract the frequencies of the words
def parse_colfis():
    word_frequency_list = []
    with open(colfis_frequencies_path, 'r', encoding="iso-8859-1") as file:
        print(f"Loaded '{colfis_frequencies_path}'")
        lines = file.readlines()
        for line in lines:
            words = line.strip().split()
            words[0] = words[0].strip()
            if not (words[1].isdigit() and words[2].isdigit()):
                continue
            if re.search(r"[-.,!?;:']", words[0]):
                continue
            if not (words[0] in big_word_set or words[0] in wiktionary_set):
                continue
            word_frequency_list.append({"word": words[0], "frequency": words[1]})
    print(f"CoLFIS successfully parsed [{len(word_frequency_list)} words]")
    return word_frequency_list

def build_list():
    result_list = []
    result_set = set()
    for word_accent in wiktionary_words_accents:
        result_set.add(word_accent["word"])
        colfis_index = next(
            (i for i, item in enumerate(colfis_words_frequency) if item["word"] == word_accent["word"])
            , None
        )
        current_frequency = 0
        if colfis_index != None:
            current_frequency = colfis_words_frequency[colfis_index]["frequency"]
        if word_accent["accent2"] == None:
            result_list.append(
                [word_accent["word"], word_accent["accent1"], current_frequency]
            )
        else:
            result_list.append(
                [word_accent["word"], word_accent["accent1"], current_frequency]
            )
            result_list.append(
                [word_accent["word"], word_accent["accent2"], current_frequency]
            )
    for word_frequency in colfis_words_frequency:
        if word_frequency["word"] not in result_set:
            result_list.append(
                [word_frequency["word"], None, word_frequency["frequency"]]
            )
    print(f"Word list built [{len(result_list)} words]")
    return result_list

# Use espeak to find the missing accents in the words
def find_missing_accents(result_list):

    def get_phonetics(word):
        result = subprocess.run(['espeak', '-x', '-q', '-v', 'it', word], capture_output=True, text=True, check=True)
        word = result.stdout.strip().lower()
        # Restore the vowel 'u'
        return re.sub(r"w2?", "u", word)

    def find_accent_in_phonetics(phonetics):
        accented_vowel_index = 0
        accent_found = False
        for letter in phonetics:
            if letter in "aeiouàèìòùáéíóú":
                accented_vowel_index += 1
            elif letter == "'":
                accent_found = True
                break
        return accented_vowel_index if accent_found else None

    def get_accent_index(word):
        # If the word contains the letter 'w', we won't be able to extract the accent,
        # so let's exclude all of the foreign letters for consistency
        if re.search(r"[wyjkx]", item[0]):
            return None
        phonetics = get_phonetics(word)
        accented_vowel_index = find_accent_in_phonetics(phonetics)
        if accented_vowel_index == None:
            print(f"Error: accent not found in word '{word}' [{phonetics}]")
            return None
        last_vowel_index = 0
        for iii, letter in enumerate(word):
            if letter in "aeiouàèìòùáéíóú":
                if last_vowel_index == accented_vowel_index:
                    return iii
                last_vowel_index += 1
        print(f"Error: phonetics vowels don't match in word '{word}' [{phonetics}]")
        return None

    final_list = []
    for item in result_list:
        if item[1] != None:
            final_list.append(item)
        else:
            item[1] = get_accent_index(item[0])
            if item[1]!= None:
                final_list.append(item)
    print(f"Missing accents found [{len(final_list)} words]")
    return final_list

def sort_and_save_final_list(final_list):
    with open(compiled_dictionary_path, 'w', encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        # Sort the list in alphabetical order of the REVERSED word string (to make binary search possible)
        # This actually sorts accented letters in the wrong order, but for our purposes it doesn't matter
        writer.writerows(sorted(final_list, key=lambda x: x[0][::-1]))
    print(f"Written '{compiled_dictionary_path}'")

script_start_time = time.time()
big_word_set = load_big_word_set()
wiktionary_set, wiktionary_words_accents = parse_wiktionary()
colfis_words_frequency = parse_colfis()
sort_and_save_final_list(find_missing_accents(build_list()))
print(f"Execution time: {str(timedelta(seconds=time.time() - script_start_time))}")
