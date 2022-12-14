from settings import VECTOR_SIZE
from utils import choose
from utils_graph import get_random_corrupted_triple
import torch
from tokenizers.models import WordLevel
from tokenizers import Tokenizer
from transformers import BertTokenizer, EncoderDecoderModel, BertForTokenClassification
from tokenizers.pre_tokenizers import WhitespaceSplit
from tokenizers.trainers import WordLevelTrainer
from tokenizers.processors import BertProcessing
from transformers import BertConfig, BertModel, AutoModel

import numpy as np

class Dataset11(torch.utils.data.Dataset):
    def __init__(self, graph, vec_mapping, entities, corrupt='random', vector_size=VECTOR_SIZE):
        """
        graph: graph to train on
        vec_mapping: function that returns vectos from URIs
        entities: iterable of all entities to build fake triples
        """

        self.entities = vec_mapping(np.array(entities))
        self.graph = get_vectors_fast(graph, vec_mapping)
        self.len = len(graph)
        self.vec_mapping = vec_mapping
        self.corrupt = corrupt
        self.vector_size = vector_size

    def __len__(self):
        return self.len

    def __getitem__(self, ix):
        return get_1_1_dataset_embedded(self.graph[ix], self.entities, self.corrupt, self.vector_size)


def random_mask(token, mask_token, vocab_size, mask_chance=0.15, mask_token_chance=0.9):
    mask_roll = torch.rand(())
    if mask_roll < mask_chance:
        mask_token_roll = torch.rand(())
        if mask_token_roll < mask_token_chance:
            return mask_token, 1
        else:
            return torch.randint(high=vocab_size, size=()), 2

    else:
        return token, 0


def mask_list_of_lists(l, mask_token, vocab_size, special_token_ids):
    # get random mask for each token, but not for special tokens
    return torch.tensor(
        [[random_mask(y, mask_token, vocab_size) if y not in special_token_ids else y for y in x] for x in l])


def mask_list(l, mask_token, vocab_size, special_token_ids):
    # get random mask for each token, but not for special tokens
    return torch.tensor([random_mask(y, mask_token, vocab_size) if y not in special_token_ids else (y, 0) for y in l])

class DataseSimpleTriple(torch.utils.data.Dataset):
    def __init__(self, triples, special_tokens_map, max_length=128):


        word_level_tokenizer = Tokenizer(WordLevel(unk_token=special_tokens_map['unk_token']))
        word_level_trainer = WordLevelTrainer(special_tokens=list(special_tokens_map.values()))
        # Pretokenizer. This is important and could lead to better/worse results!
        word_level_tokenizer.pre_tokenizer = WhitespaceSplit()

        word_level_tokenizer.train_from_iterator(triples, word_level_trainer)

        word_level_tokenizer.post_processor = BertProcessing(
            ("[SEP]", word_level_tokenizer.token_to_id("[SEP]")),
            ('[CLS]', word_level_tokenizer.token_to_id('[CLS]')),
        )

        self.mask_token_id = word_level_tokenizer.token_to_id(special_tokens_map['mask_token'])
        word_level_tokenizer.enable_truncation(max_length=max_length)
        self.labels = torch.tensor([x.ids for x in word_level_tokenizer.encode_batch(triples)])

        self.special_token_ids = [word_level_tokenizer.token_to_id(x) for x in special_tokens_map.values()]

        self.attention_masks = torch.stack([torch.ones(len(x)) for x in self.labels])
        self.word_level_tokenizer = word_level_tokenizer

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        return mask_list(self.labels[i], self.mask_token_id,
                         self.word_level_tokenizer.get_vocab_size(), self.special_token_ids), self.attention_masks[i], \
               self.labels[i]

    def get_tokenizer(self):
        return self.word_level_tokenizer


def get_1_1_dataset(graph, entities, entity_vec_mapping, corrupt='random'):
    original_triple_len = len(graph)
    # get triples
    X = list(graph)
    no_t = len(X)

    corrupted_triples = [get_random_corrupted_triple(x, entities, corrupt=corrupt) for x in X]
    X = X + corrupted_triples

    # convert uris to strings

    X = get_vectors_fast(X, entity_vec_mapping)

    # stack them

    Y = np.concatenate((np.ones(no_t), np.zeros(no_t))).astype(np.uint8)

    return X, Y


def get_1_1_dataset_embedded(graph, entities, corrupt='random', vector_size=VECTOR_SIZE):
    """
    graph: numpy array of shape (samples,3*vecsize)
    """

    if len(graph.shape) == 1:
        graph = np.expand_dims(graph, 0)
    # print(graph.shape)
    no_t = len(graph)
    corrupted_triples = [get_random_corrupted_triple_embedded(x, entities, corrupt=corrupt, vector_size=vector_size) for
                         x in graph]
    X = np.concatenate((graph, corrupted_triples), axis=0)

    Y = np.concatenate((np.ones(no_t), np.zeros(no_t))).astype(np.uint8)

    return X, Y


def get_vectors_fast(triples, entity_vec_mapping, vector_size=VECTOR_SIZE):
    # ~20-30% faster
    X = np.array(triples)
    X = entity_vec_mapping(X.flatten()).reshape(len(triples), vector_size * 3)


    return X


def get_random_corrupted_triple_embedded(triple, entities, corrupt='object', vector_size=VECTOR_SIZE):
    """
    corrupt = one of 'subject', 'object', 'both'

    return corrupted triple with random entity
    """

    s = triple[0:VECTOR_SIZE]
    p = triple[VECTOR_SIZE:VECTOR_SIZE * 2]
    o = triple[VECTOR_SIZE * 2:]

    # set up as the same
    s_corr = s[:]
    o_corr = o[:]

    if corrupt == 'subject':

        # corrupt only the subject
        while (s_corr == s).all():
            s_corr = choose(entities)
    elif corrupt == 'object':
        # corrupt only the object
        while (o_corr == o).all():
            o_corr = choose(entities)
    elif corrupt == 'random':
        # corrupt one or both randomly
        ch = np.random.randint(3)

        if ch == 0:
            while (s_corr == s).all():
                s_corr = choose(entities)
        if ch == 1:
            while (o_corr == o).all():
                o_corr = choose(entities)
        if ch == 2:

            while (s_corr == s).all() or (o_corr == o).all():
                s_corr = choose(entities)
                o_corr = choose(entities)
    else:

        while (s_corr == s).all() or (o_corr == o).all():
            s_corr = choose(entities)
            o_corr = choose(entities)

    return np.concatenate((s_corr, p, o_corr), axis=0)


def get_bert_simple_dataset(graph):


    # Just 's p o' as sentence.
    dataset_most_simple = [' '.join(x) for x in graph]

    # get special BERT tokens
    tz = BertTokenizer.from_pretrained("bert-base-cased")

    special_tokens_map = tz.special_tokens_map_extended

    del(tz)

    dataset = DataseSimpleTriple(dataset_most_simple,special_tokens_map)
    tz = dataset.get_tokenizer()

    return dataset, tz
